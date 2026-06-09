"""PaperExecutor tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import AutonomyMode, EventEnvelope, EventType
from portfolio.executor import PaperExecutor
from portfolio.ledger import Portfolio


@pytest.fixture
async def bus() -> InProcessBus:
    return InProcessBus(store=InMemoryEventStore())


@pytest.fixture
async def portfolio(bus: InProcessBus) -> Portfolio:
    p = Portfolio(bus)
    await p.start()
    return p


def _tick(instrument: str, price: str) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.MARKET_TICK,
        source="test",
        event_time=datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={"instrument": instrument, "price": price, "volume": "1"},
    )


def _approved(instrument: str = "BTC-USD", size_usd: str = "500") -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.DECISION_APPROVED,
        source="test",
        event_time=datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={
            "id": str(uuid4()),
            "proposal": {"instrument": instrument, "side": "long", "size_usd": size_usd},
            "risk": {"stop_price": None, "rejection_reasons": []},
            "status": "approved",
        },
    )


async def test_paper_mode_auto_fills(bus: InProcessBus, portfolio: Portfolio) -> None:
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))

    await bus.publish(_approved("BTC-USD", "500"))
    assert len(fills) == 1
    assert fills[0].payload["action"] == "open"

    await executor.stop()


async def test_observe_mode_ignores(bus: InProcessBus, portfolio: Portfolio) -> None:
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.OBSERVE)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))

    await bus.publish(_approved("BTC-USD", "500"))
    assert len(fills) == 0

    await executor.stop()


async def test_assisted_mode_parks(bus: InProcessBus, portfolio: Portfolio) -> None:
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.ASSISTED)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))

    env = _approved("BTC-USD", "500")
    decision_id = env.payload["id"]
    await bus.publish(env)

    assert len(fills) == 0
    assert len(executor.pending_decisions) == 1

    ok = await executor.execute(decision_id)
    assert ok is True
    assert len(fills) == 1

    await executor.stop()
