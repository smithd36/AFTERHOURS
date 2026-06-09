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
) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.ORDER_FILLED,
        source="test",
        event_time=datetime.now(UTC),
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
    realized = portfolio.daily_realized_pnl
    assert realized == Decimal("97.9")  # 2100 - 2000 - 2.1


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
