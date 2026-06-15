"""FeedHealth: emits system.feed_* only on status transitions."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType
from ingestion.health import FeedHealth


@pytest.fixture
async def bus() -> AsyncIterator[InProcessBus]:
    b = InProcessBus(InMemoryEventStore())
    yield b
    await b.close()


async def _collect(bus: InProcessBus) -> list[EventEnvelope]:
    got: list[EventEnvelope] = []

    async def handler(env: EventEnvelope) -> None:
        got.append(env)

    await bus.subscribe(EventType.SYSTEM_FEED_HEALTHY, handler)
    await bus.subscribe(EventType.SYSTEM_FEED_DEGRADED, handler)
    return got


async def test_first_report_announces_then_dedups(bus: InProcessBus) -> None:
    got = await _collect(bus)
    h = FeedHealth(bus, "news")

    await h.report_healthy()
    await h.report_healthy()  # no change → no second event

    assert len(got) == 1
    assert got[0].event_type == EventType.SYSTEM_FEED_HEALTHY.value
    assert got[0].payload == {"feed_id": "news", "status": "healthy", "detail": ""}


async def test_transition_healthy_to_degraded_and_back(bus: InProcessBus) -> None:
    got = await _collect(bus)
    h = FeedHealth(bus, "gov_contracts")

    await h.report_healthy()
    await h.report_degraded("400 Bad Request")
    await h.report_healthy()

    assert [e.event_type for e in got] == [
        EventType.SYSTEM_FEED_HEALTHY.value,
        EventType.SYSTEM_FEED_DEGRADED.value,
        EventType.SYSTEM_FEED_HEALTHY.value,
    ]
    assert got[1].payload["detail"] == "400 Bad Request"


async def test_commit_degraded_when_all_fetches_fail(bus: InProcessBus) -> None:
    got = await _collect(bus)
    h = FeedHealth(bus, "gov_contracts")

    # A cycle where every per-target fetch failed (the silent bug) → degraded.
    h.fetch_failed("400")
    h.fetch_failed("400")
    await h.commit()

    assert len(got) == 1
    assert got[0].event_type == EventType.SYSTEM_FEED_DEGRADED.value
    assert got[0].payload["detail"] == "400"


async def test_commit_healthy_when_any_fetch_succeeds(bus: InProcessBus) -> None:
    got = await _collect(bus)
    h = FeedHealth(bus, "gov_contracts")

    h.fetch_ok()  # lobbying worked even though...
    h.fetch_failed("400")  # ...a target failed → feed is still up
    await h.commit()

    assert len(got) == 1
    assert got[0].event_type == EventType.SYSTEM_FEED_HEALTHY.value


async def test_commit_with_no_attempts_emits_nothing(bus: InProcessBus) -> None:
    got = await _collect(bus)
    h = FeedHealth(bus, "supply_chain")

    await h.commit()  # nothing to poll this cycle → status unchanged

    assert got == []
