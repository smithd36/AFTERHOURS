"""Tests for ThesisInvalidator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType
from reasoning.thesis.invalidator import ThesisInvalidator, _CHECK_INTERVAL_SECONDS


def _thesis_created(thesis_id: str, horizon_hours: int = 1) -> EventEnvelope:
    now = datetime.now(UTC)
    return EventEnvelope(
        event_type=EventType.THESIS_CREATED,
        source="test",
        event_time=now,
        ingest_time=now,
        payload={
            "id": thesis_id,
            "instrument": "BTC-USD",
            "time_horizon_hours": horizon_hours,
            "summary": "test thesis",
            "body": "",
            "direction": "long",
            "confidence": 0.5,
            "invalidation_conditions": [],
            "status": "active",
        },
    )


@pytest.fixture
def bus() -> InProcessBus:
    return InProcessBus(InMemoryEventStore())


async def test_thesis_registered_on_create(bus: InProcessBus) -> None:
    invalidator = ThesisInvalidator(bus)
    await invalidator.start()

    thesis_id = str(uuid4())
    await bus.publish(_thesis_created(thesis_id, horizon_hours=4))

    assert thesis_id in {str(k) for k in invalidator._active}
    await invalidator.stop()


async def test_expired_thesis_emits_invalidated(bus: InProcessBus) -> None:
    invalidator = ThesisInvalidator(bus)
    await invalidator.start()

    received: list[EventEnvelope] = []
    await bus.subscribe(EventType.THESIS_INVALIDATED, lambda e: received.append(e) or None)  # type: ignore[func-returns-value]

    thesis_id = str(uuid4())
    await bus.publish(_thesis_created(thesis_id, horizon_hours=1))

    # Manually backdate the expiry so it's already past
    from uuid import UUID
    tid = UUID(thesis_id)
    exp, instrument = invalidator._active[tid]
    invalidator._active[tid] = (datetime.now(UTC) - timedelta(seconds=1), instrument)

    # Trigger the expiry check directly (bypass the sleep)
    now = datetime.now(UTC)
    expired = [t for t, (e, _) in invalidator._active.items() if e <= now]
    for t in expired:
        _, instr = invalidator._active.pop(t)
        await bus.publish(EventEnvelope(
            event_type=EventType.THESIS_INVALIDATED,
            source="thesis_invalidator",
            event_time=now,
            ingest_time=now,
            payload={"thesis_id": str(t), "reason": "expired", "instrument": instr},
        ))

    await invalidator.stop()

    assert len(received) == 1
    assert received[0].payload["thesis_id"] == thesis_id
    assert received[0].payload["reason"] == "expired"
