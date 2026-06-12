"""RiskEngine integration tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import AutonomyMode, EventEnvelope, EventType
from portfolio.ledger import Portfolio
from risk.engine import RiskEngine


def _proposed_envelope(instrument: str = "BTC-USD") -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.DECISION_PROPOSED,
        source="test",
        event_time=datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={
            "id": str(uuid4()),
            "proposal": {"instrument": instrument, "side": "long", "size_usd": "0"},
            "reasoning": "test",
            "confidence": 0.7,
            "status": "proposed",
        },
    )


def _proposed_at(instrument: str, event_time: datetime) -> EventEnvelope:
    env = _proposed_envelope(instrument)
    return env.model_copy(update={"event_time": event_time})


async def _realize_loss(bus: InProcessBus, instrument: str, event_time: datetime) -> None:
    """Open and close a position at a loss on `event_time`'s UTC day (~$600 loss)."""
    for action, price in (("open", "1000"), ("close", "400")):
        await bus.publish(EventEnvelope(
            event_type=EventType.ORDER_FILLED,
            source="test",
            event_time=event_time,
            ingest_time=datetime.now(UTC),
            payload={
                "instrument": instrument, "action": action, "side": "long",
                "fill_price": price, "quantity": "1", "cost_usd": "1000",
                "fee": "0", "stop_price": None, "decision_id": "seed",
            },
        ))


def _tick_envelope(instrument: str, price: str) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.MARKET_TICK,
        source="test",
        event_time=datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={"instrument": instrument, "price": price, "volume": "1"},
    )


@pytest.fixture
async def bus() -> InProcessBus:
    b = InProcessBus(store=InMemoryEventStore())
    return b


@pytest.fixture
async def portfolio(bus: InProcessBus) -> Portfolio:
    p = Portfolio(bus)
    await p.start()
    return p


async def test_observe_mode_rejects_all(bus: InProcessBus, portfolio: Portfolio) -> None:
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.OBSERVE)
    await engine.start()

    rejected: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_REJECTED, lambda e: rejected.append(e))

    await bus.publish(_proposed_envelope())
    assert len(rejected) == 1
    reasons = rejected[0].payload["risk"]["rejection_reasons"]
    assert any("observe_mode" in r for r in reasons)

    await engine.stop()


async def test_paper_mode_approves_with_price(bus: InProcessBus, portfolio: Portfolio) -> None:
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await engine.start()

    # Seed price
    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    approved: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_APPROVED, lambda e: approved.append(e))

    await bus.publish(_proposed_envelope("BTC-USD"))

    assert len(approved) == 1
    size = Decimal(approved[0].payload["proposal"]["size_usd"])
    assert size > 0

    await engine.stop()


async def test_max_positions_rejected(bus: InProcessBus, portfolio: Portfolio) -> None:
    from risk.settings import RiskSettings
    settings = RiskSettings(max_open_positions=0)  # artificially 0
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER, settings=settings)
    await engine.start()

    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    rejected: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_REJECTED, lambda e: rejected.append(e))

    await bus.publish(_proposed_envelope("BTC-USD"))
    assert len(rejected) == 1
    reasons = rejected[0].payload["risk"]["rejection_reasons"]
    assert any("max_open_positions" in r for r in reasons)

    await engine.stop()


async def test_daily_loss_breaker_trips_same_day(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A loss exceeding max_daily_loss_pct on the proposal's own day blocks entry."""
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await engine.start()

    day = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    await _realize_loss(bus, "ETH-USD", day)  # ~6% of a 10k book
    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    rejected: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_REJECTED, lambda e: rejected.append(e))

    await bus.publish(_proposed_at("BTC-USD", day))
    assert len(rejected) == 1
    reasons = rejected[0].payload["risk"]["rejection_reasons"]
    assert any("daily_loss_limit" in r for r in reasons)

    await engine.stop()


async def test_daily_loss_breaker_resets_next_day(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """Yesterday's realized loss must not block a fresh-day entry (the reported bug)."""
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await engine.start()

    yesterday = datetime(2026, 3, 1, 20, 0, tzinfo=UTC)
    today = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
    await _realize_loss(bus, "ETH-USD", yesterday)
    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    approved: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_APPROVED, lambda e: approved.append(e))

    await bus.publish(_proposed_at("BTC-USD", today))
    assert len(approved) == 1  # not blocked by yesterday's loss

    await engine.stop()


async def test_mode_change_via_event(bus: InProcessBus, portfolio: Portfolio) -> None:
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.OBSERVE)
    await engine.start()

    # Change to PAPER via event
    now = datetime.now(UTC)
    await bus.publish(EventEnvelope(
        event_type=EventType.SYSTEM_MODE_CHANGED,
        source="test",
        event_time=now,
        ingest_time=now,
        payload={"from_mode": "observe", "to_mode": "paper", "actor": "test", "reason": ""},
    ))

    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    approved: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_APPROVED, lambda e: approved.append(e))

    await bus.publish(_proposed_envelope("BTC-USD"))
    assert len(approved) == 1

    await engine.stop()
