"""GateTracker tests — autonomy graduation evidence that must survive restarts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from calibration.engine import CalibrationEngine
from calibration.gates import GateTracker
from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType


@pytest.fixture
async def bus() -> InProcessBus:
    return InProcessBus(store=InMemoryEventStore())


def _breach(instrument: str = "BTC-USD") -> EventEnvelope:
    now = datetime.now(UTC)
    return EventEnvelope(
        event_type=EventType.RISK_LIMIT_BREACHED,
        source="risk_engine",
        event_time=now,
        ingest_time=now,
        payload={"instrument": instrument, "reason": "stop_loss"},
    )


def _breach_count(tracker: GateTracker) -> str:
    """The risk_limit_breaches criterion's reported current value."""
    criteria = tracker.report()["paper_to_assisted"]["criteria"]
    return next(c["current"] for c in criteria if c["name"] == "risk_limit_breaches")


async def test_seed_restores_breach_count(bus: InProcessBus) -> None:
    """Persisted breaches must be restored, not forgotten — a reset count would
    silently pass the '0 breaches' gate after a restart."""
    tracker = GateTracker(bus, CalibrationEngine(bus))
    tracker.seed([_breach(), _breach()])
    await tracker.start()

    assert _breach_count(tracker) == "2"

    # A live breach after seeding accumulates on top, not double-counted.
    await bus.publish(_breach())
    assert _breach_count(tracker) == "3"

    await tracker.stop()


async def test_unseeded_tracker_starts_at_zero(bus: InProcessBus) -> None:
    tracker = GateTracker(bus, CalibrationEngine(bus))
    await tracker.start()
    assert _breach_count(tracker) == "0"
    await tracker.stop()
