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

    async def test_payload_type_filter(self, store: SqliteEventStore) -> None:
        # News dominates; payload_type isolates the sparse alt-data subtype.
        for i in range(5):
            await store.append(_envelope("signal.created", i, {"type": "news"}))
        await store.append(_envelope("signal.created", 5, {"type": "supply_chain"}))

        result = await store.recent(
            ["signal.created"], limit=10, payload_type=["supply_chain", "insider_tx"]
        )
        assert [e.payload["type"] for e in result] == ["supply_chain"]

    async def test_round_trips_envelope_fields(self, store: SqliteEventStore) -> None:
        original = _envelope("thesis.created", 0, {"id": "t1", "nested": {"k": "v"}})
        await store.append(original)

        [restored] = await store.recent(["thesis.created"])
        assert restored.id == original.id
        assert restored.event_time == original.event_time
        assert restored.payload == original.payload


class TestRange:
    T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    async def test_window_bounds_inclusive(self, store: SqliteEventStore) -> None:
        for i in range(5):
            await store.append(_envelope("market.tick", i * 60, {"i": i}))

        result = await store.range(
            ["market.tick"],
            start=self.T0 + timedelta(minutes=1),
            end=self.T0 + timedelta(minutes=3),
        )
        assert [e.payload["i"] for e in result] == [1, 2, 3]

    async def test_unbounded_returns_all_chronological(self, store: SqliteEventStore) -> None:
        await store.append(_envelope("market.tick", 30, {"i": "late"}))
        await store.append(_envelope("market.tick", 0, {"i": "early"}))

        result = await store.range(["market.tick"])
        assert [e.payload["i"] for e in result] == ["early", "late"]

    async def test_filters_types(self, store: SqliteEventStore) -> None:
        await store.append(_envelope("market.tick", 0, {"i": 0}))
        await store.append(_envelope("signal.created", 1, {"id": "s"}))

        result = await store.range(["market.tick", "signal.created"])
        assert [e.event_type for e in result] == ["market.tick", "signal.created"]
        assert await store.range([]) == []


class TestLatestPerKey:
    async def test_returns_newest_per_instrument(self, store: SqliteEventStore) -> None:
        await store.append(_envelope("market.tick", 0, {"instrument": "BTC", "price": "1"}))
        await store.append(_envelope("market.tick", 60, {"instrument": "BTC", "price": "2"}))
        await store.append(_envelope("market.tick", 30, {"instrument": "ETH", "price": "9"}))

        result = await store.latest_per_key(["market.tick"], "instrument")
        assert set(result) == {"BTC", "ETH"}
        assert result["BTC"].payload["price"] == "2"  # the later tick
        assert result["ETH"].payload["price"] == "9"

    async def test_ignores_other_types_and_missing_key(self, store: SqliteEventStore) -> None:
        await store.append(_envelope("market.tick", 0, {"instrument": "BTC", "price": "1"}))
        await store.append(_envelope("signal.created", 1, {"instrument": "BTC"}))
        await store.append(_envelope("market.tick", 2, {"price": "no-instrument"}))

        result = await store.latest_per_key(["market.tick"], "instrument")
        assert set(result) == {"BTC"}
        assert result["BTC"].payload["price"] == "1"

    async def test_empty_types(self, store: SqliteEventStore) -> None:
        assert await store.latest_per_key([], "instrument") == {}

    async def test_rejects_bad_key_field(self, store: SqliteEventStore) -> None:
        with pytest.raises(ValueError):
            await store.latest_per_key(["market.tick"], "x'; DROP TABLE events;--")
