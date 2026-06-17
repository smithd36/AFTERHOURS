"""The projection: only unwatched instruments, within the window, above
threshold, ranked — over real persisted signal.created events."""

from datetime import UTC, datetime, timedelta

import pytest

from core.bus.store import InMemoryEventStore
from core.schemas.events import EventEnvelope, EventType
from discovery import DiscoverySettings, build_candidates

NOW = datetime(2026, 6, 16, tzinfo=UTC)


def _signal_event(instrument, factor, *, relevance=0.9, direction="buy", age_days=0.0):
    """A signal.created envelope shaped like a dumped Signal (see normalizers)."""
    t = NOW - timedelta(days=age_days)
    return EventEnvelope(
        event_type=EventType.SIGNAL_CREATED,
        source="test",
        event_time=t,
        ingest_time=t,
        payload={
            "type": "insider_tx",
            "instruments": [instrument],
            "relevance_score": relevance,
            "payload": {
                "summary": f"{factor} on {instrument}",
                "factor": factor,
                "direction": direction,
            },
        },
    )


async def _store(*events):
    store = InMemoryEventStore()
    for e in events:
        await store.append(e)
    return store


@pytest.mark.asyncio
async def test_watched_instruments_are_excluded():
    store = await _store(
        _signal_event("AAA", "insider_activity"),
        _signal_event("BBB", "insider_activity"),
    )
    out = await build_candidates(
        store, watched={"BBB"}, now=NOW, settings=DiscoverySettings()
    )
    assert [c.instrument for c in out] == ["AAA"]


@pytest.mark.asyncio
async def test_stale_signals_outside_the_window_are_ignored():
    settings = DiscoverySettings(window_days=30)
    store = await _store(_signal_event("AAA", "insider_activity", age_days=90))
    out = await build_candidates(store, watched=set(), now=NOW, settings=settings)
    assert out == []


@pytest.mark.asyncio
async def test_below_threshold_is_dropped_and_results_ranked():
    settings = DiscoverySettings(threshold=0.3)
    store = await _store(
        # Strong confluence on AAA (two factors), weak single signal on CCC.
        _signal_event("AAA", "insider_activity", relevance=0.8),
        _signal_event("AAA", "government_exposure", relevance=0.8),
        _signal_event("CCC", "supply_chain", relevance=0.1, direction="neutral"),
    )
    out = await build_candidates(store, watched=set(), now=NOW, settings=settings)
    assert [c.instrument for c in out] == ["AAA"]
    assert out[0].score >= settings.threshold
