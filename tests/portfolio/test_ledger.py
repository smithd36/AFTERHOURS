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


async def test_realized_pnl_includes_entry_fee_long(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A break-even exit must realize both fees, not just the close fee — the
    entry fee was paid from cash at open and belongs in the cost basis."""
    initial = portfolio.cash
    # Open long: notional 1000 (100 x 10), entry fee 1.
    await bus.publish(_fill_event("BTC-USD", "open", "long", "100", "10", "1000", fee="1"))
    # Close at break-even price (100), close fee 1.
    await bus.publish(_fill_event("BTC-USD", "close", "long", "100", "10", "0", fee="1"))

    realized = portfolio.daily_realized_pnl(datetime.now(UTC))
    assert realized == Decimal("-2")  # entry fee + close fee, not -1
    # Conservation: realized P&L equals the net change in cash over the round trip.
    assert portfolio.cash - initial == realized


async def test_realized_pnl_includes_entry_fee_short(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """The short leg must book the entry fee into realized P&L too."""
    initial = portfolio.cash
    await bus.publish(_fill_event("ETH-USD", "open", "short", "100", "10", "1000", fee="1"))
    await bus.publish(_fill_event("ETH-USD", "close", "short", "100", "10", "0", fee="1"))

    realized = portfolio.daily_realized_pnl(datetime.now(UTC))
    assert realized == Decimal("-2")
    assert portfolio.cash - initial == realized


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


async def test_rehydrate_rebuilds_cash_positions_and_daily_pnl(bus: InProcessBus) -> None:
    """A fresh portfolio replays the persisted fill history into the same cash,
    open positions and daily-P&L state it would have had without a restart."""
    day = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    history = [
        # Open BTC and leave it open.
        _fill_event("BTC-USD", "open", "long", "50000", "0.01", "500", fee="0.5",
                    stop_price="48500", event_time=day),
        # Open ETH then close it at a $100 loss the same day.
        _fill_event("ETH-USD", "open", "long", "2000", "1", "2000", event_time=day),
        _fill_event("ETH-USD", "close", "long", "1900", "1", "0", event_time=day),
    ]

    fresh = Portfolio(bus)
    assert fresh.cash == Decimal("10000.00")  # initial_cash, pre-rehydrate
    await fresh.rehydrate(history)

    # Cash: 10000 -500.5 (BTC open+fee) -2000 (ETH open) +1900 (ETH close) = 9399.5
    assert fresh.cash == Decimal("9399.5")
    assert "BTC-USD" in fresh.positions
    assert fresh.positions["BTC-USD"].stop_price == Decimal("48500")  # stop survives restart
    assert "ETH-USD" not in fresh.positions
    assert fresh.open_position_count == 1
    # The realized day-1 loss is preserved for the daily breaker.
    assert fresh.daily_realized_pnl(day) == Decimal("-100")


async def test_rehydrate_equivalent_to_live_application(bus: InProcessBus) -> None:
    """Rehydration is the live fill path replayed: both end in identical state."""
    day = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
    history = [
        _fill_event("BTC-USD", "open", "long", "100", "1", "100", fee="0.1", event_time=day),
        _fill_event("BTC-USD", "close", "long", "120", "1", "0", fee="0.12", event_time=day),
        _fill_event("SOL-USD", "open", "long", "50", "2", "100", event_time=day),
    ]

    live = Portfolio(bus)
    await live.start()
    for env in history:
        await bus.publish(env)

    rehydrated = Portfolio(bus)
    await rehydrated.rehydrate(history)

    assert rehydrated.cash == live.cash
    assert set(rehydrated.positions) == set(live.positions)
    assert rehydrated.daily_realized_pnl(day) == live.daily_realized_pnl(day)

    await live.stop()


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
