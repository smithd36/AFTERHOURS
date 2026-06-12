"""PaperExecutor tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import AutonomyMode, EventEnvelope, EventType
from portfolio.executor import HaltedError, PaperExecutor
from portfolio.ledger import Portfolio


def _halt(reason: str = "operator_halt") -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.RISK_HALT,
        source="operator",
        event_time=datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={"reason": reason, "scope": "all", "actor": "operator"},
    )


def _mode_changed(to_mode: AutonomyMode) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.SYSTEM_MODE_CHANGED,
        source="operator",
        event_time=datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={"from_mode": "assisted", "to_mode": to_mode.value, "actor": "operator"},
    )


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


async def test_halt_expires_pending_and_blocks_execution(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """The kill switch must flush the queue and refuse any later execute()."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.ASSISTED)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    fills: list[EventEnvelope] = []
    expired: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))
    await bus.subscribe(EventType.DECISION_EXPIRED, lambda e: expired.append(e))

    env = _approved("BTC-USD", "500")
    decision_id = env.payload["id"]
    await bus.publish(env)
    assert len(executor.pending_decisions) == 1

    # Kill switch fires.
    await bus.publish(_halt())

    # Queue is flushed with an audited decision.expired carrying the decision id.
    assert len(executor.pending_decisions) == 0
    assert len(expired) == 1
    assert expired[0].payload["decision_id"] == decision_id
    assert str(expired[0].correlation_id) == decision_id

    # The parked decision can no longer be executed — kill-switch bypass closed.
    with pytest.raises(HaltedError):
        await executor.execute(decision_id)
    assert len(fills) == 0

    await executor.stop()


async def test_mode_demotion_expires_pending(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """Demotion below ASSISTED expires parked decisions even without a halt."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.ASSISTED)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    expired: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_EXPIRED, lambda e: expired.append(e))

    await bus.publish(_approved("BTC-USD", "500"))
    assert len(executor.pending_decisions) == 1

    await bus.publish(_mode_changed(AutonomyMode.OBSERVE))
    assert len(executor.pending_decisions) == 0
    assert len(expired) == 1

    await executor.stop()


async def test_execute_refused_in_observe(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """execute() refuses outright when authority is below ASSISTED."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.OBSERVE)
    await executor.start()

    with pytest.raises(HaltedError):
        await executor.execute("does-not-matter")

    await executor.stop()
