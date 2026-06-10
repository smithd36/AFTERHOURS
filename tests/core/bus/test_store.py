"""
Tests for SqliteEventStore.recent() against a real in-memory SQLite DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.bus.store import SqliteEventStore
from core.db import migrate, open_db
from core.schemas.events import EventEnvelope


def _envelope(event_type: str, offset_seconds: int, payload: dict) -> EventEnvelope:
    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_seconds)
    return EventEnvelope(
        event_type=event_type,
        source="test",
        event_time=ts,
        ingest_time=ts,
        payload=payload,
    )


@pytest.fixture
async def store():
    conn = await open_db(":memory:")
    await migrate(conn)
    s = SqliteEventStore(conn)
    yield s
    await s.close()


class TestRecent:
    async def test_empty_types_returns_nothing(self, store: SqliteEventStore) -> None:
        await store.append(_envelope("signal.created", 0, {"id": "a"}))
        assert await store.recent([]) == []

    async def test_filters_by_type(self, store: SqliteEventStore) -> None:
        await store.append(_envelope("market.tick", 0, {"instrument": "BTC-USD"}))
        await store.append(_envelope("signal.created", 1, {"id": "a"}))

        result = await store.recent(["signal.created"])
        assert [e.event_type for e in result] == ["signal.created"]

    async def test_chronological_order(self, store: SqliteEventStore) -> None:
        await store.append(_envelope("signal.created", 0, {"id": "first"}))
        await store.append(_envelope("signal.created", 10, {"id": "second"}))

        result = await store.recent(["signal.created"])
        assert [e.payload["id"] for e in result] == ["first", "second"]

    async def test_limit_keeps_newest(self, store: SqliteEventStore) -> None:
        for i in range(5):
            await store.append(_envelope("signal.created", i, {"id": f"s{i}"}))

        result = await store.recent(["signal.created"], limit=2)
        assert [e.payload["id"] for e in result] == ["s3", "s4"]

    async def test_round_trips_envelope_fields(self, store: SqliteEventStore) -> None:
        original = _envelope("thesis.created", 0, {"id": "t1", "nested": {"k": "v"}})
        await store.append(original)

        [restored] = await store.recent(["thesis.created"])
        assert restored.id == original.id
        assert restored.event_time == original.event_time
        assert restored.payload == original.payload
