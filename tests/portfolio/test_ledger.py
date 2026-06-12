"""Portfolio ledger tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.decision import Side
from core.schemas.events import EventEnvelope, EventType
from portfolio.ledger import Portfolio


@pytest.fixture
async def bus() -> InProcessBus:
    return InProcessBus(store=InMemoryEventStore())


@pytest.fixture
async def portfolio(bus: InProcessBus) -> Portfolio:
    p = Portfolio(bus)
    await p.start()
    return p


def _fill_event(
    instrument: str,
    action: str,
    side: str,
    fill_price: str,
    quantity: str,
    cost_usd: str,
    fee: str = "0",
    stop_price: str | None = None,
    event_time: datetime | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.ORDER_FILLED,
        source="test",
        event_time=event_time or datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={
            "instrument": instrument,
            "action": action,
            "side": side,
            "fill_price": fill_price,
            "quantity": quantity,
            "cost_usd": cost_usd,
            "fee": fee,
            "stop_price": stop_price,
            "decision_id": "test-decision",
        },
    )


async def test_open_position(bus: InProcessBus, portfolio: Portfolio) -> None:
    await bus.publish(_fill_event("BTC-USD", "open", "long", "50000", "0.01", "500"))

    assert "BTC-USD" in portfolio.positions
    pos = portfolio.positions["BTC-USD"]
    assert pos.side == Side.LONG
    assert pos.quantity == Decimal("0.01")
    assert portfolio.open_position_count == 1


async def test_cash_decreases_on_open(bus: InProcessBus, portfolio: Portfolio) -> None:
    initial = portfolio.cash
    await bus.publish(_fill_event("BTC-USD", "open", "long", "50000", "0.01", "500", fee="0.5"))

    assert portfolio.cash == initial - Decimal("500.5")


async def test_close_position_updates_cash(bus: InProcessBus, portfolio: Portfolio) -> None:
    await bus.publish(_fill_event("ETH-USD", "open", "long", "2000", "1", "2000"))
    await bus.publish(_fill_event("ETH-USD", "close", "long", "2100", "1", "0", fee="2.1"))

    assert "ETH-USD" not in portfolio.positions
    assert portfolio.open_position_count == 0
    realized = portfolio.daily_realized_pnl(datetime.now(UTC))
    assert realized == Decimal("97.9")  # 2100 - 2000 - 2.1


async def test_daily_pnl_resets_on_utc_day_rollover(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A loss realized yesterday must not count against today's daily breaker."""
    day1 = datetime(2026, 1, 1, 20, 0, tzinfo=UTC)
    day2 = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)

    # Realize a loss on day 1: buy at 2000, sell at 1900 → -100.
    await bus.publish(_fill_event("ETH-USD", "open", "long", "2000", "1", "2000",
                                  event_time=day1))
    await bus.publish(_fill_event("ETH-USD", "close", "long", "1900", "1", "0",
                                  event_time=day1))
    assert portfolio.daily_realized_pnl(day1) == Decimal("-100")

    # Same loss, queried as-of day 2 → the breaker sees a clean slate.
    assert portfolio.daily_realized_pnl(day2) == Decimal("0")

    # A new close on day 2 accumulates only the day-2 realized P&L.
    await bus.publish(_fill_event("BTC-USD", "open", "long", "100", "1", "100",
                                  event_time=day2))
    await bus.publish(_fill_event("BTC-USD", "close", "long", "110", "1", "0",
                                  event_time=day2))
    assert portfolio.daily_realized_pnl(day2) == Decimal("10")  # not 10 - 100


async def test_tick_updates_current_price(bus: InProcessBus, portfolio: Portfolio) -> None:
    await bus.publish(_fill_event("BTC-USD", "open", "long", "50000", "0.01", "500"))

    now = datetime.now(UTC)
    await bus.publish(EventEnvelope(
        event_type=EventType.MARKET_TICK,
        source="test",
        event_time=now,
        ingest_time=now,
        payload={"instrument": "BTC-USD", "price": "51000", "volume": "1"},
    ))

    assert portfolio.positions["BTC-USD"].current_price == Decimal("51000")
    assert portfolio.unrealized_pnl == Decimal("10")  # (51000 - 50000) * 0.01


async def test_total_value(bus: InProcessBus, portfolio: Portfolio) -> None:
    await bus.publish(_fill_event("BTC-USD", "open", "long", "50000", "0.01", "500"))
    # cash reduced by 500; position worth 500 → total unchanged
    assert portfolio.total_value == portfolio.cash + Decimal("500")


async def test_losing_short_decreases_total_value(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A short that loses (price rises) must *reduce* equity, not inflate it."""
    initial = portfolio.cash  # 10_000

    # Open a short: 1 unit at 2000, posting 2000 as margin.
    await bus.publish(_fill_event("ETH-USD", "open", "short", "2000", "1", "2000"))
    # No price move yet: margin + 0 P&L == cost basis, equity unchanged.
    assert portfolio.total_value == initial

    # Price rises to 2100 — a $100 loss for the short.
    now = datetime.now(UTC)
    await bus.publish(EventEnvelope(
        event_type=EventType.MARKET_TICK,
        source="test",
        event_time=now,
        ingest_time=now,
        payload={"instrument": "ETH-USD", "price": "2100", "volume": "1"},
    ))

    # equity_contribution = 2000 margin + (2000 - 2100) P&L = 1900; cash = 8000.
    assert portfolio.unrealized_pnl == Decimal("-100")
    assert portfolio.total_value == Decimal("9900")
    assert portfolio.total_value < initial  # the bug: this used to *rise* to 10100
