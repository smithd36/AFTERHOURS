"""
EventStore — durable backing for the event bus.

The bus persists every event *before* fan-out. If the process crashes
mid-fan-out, events can be replayed from the store. The store is the
source of truth for the audit log.

Two implementations:
  InMemoryEventStore  — for tests; not durable.
  SqliteEventStore    — local dev and early production; append-only.

Upgrading to Postgres: add a PostgresEventStore here that takes a
psycopg3 AsyncConnectionPool. The Bus and all callers are unchanged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

from ..schemas import EventEnvelope

if TYPE_CHECKING:
    import aiosqlite

logger = structlog.get_logger(__name__)


@runtime_checkable
class EventStore(Protocol):
    """Append-only event persistence backend."""

    async def append(self, envelope: EventEnvelope) -> None:
        """Durably write the event. Must be idempotent on duplicate id."""

    async def recent(
        self,
        event_types: list[str],
        limit: int = 200,
        payload_type: list[str] | None = None,
    ) -> list[EventEnvelope]:
        """Most-recent `limit` events of the given types, oldest-first."""

    async def prune(self, event_types: list[str], before: datetime) -> int:
        """Delete events of the given types older than `before`. Returns count deleted."""

    async def close(self) -> None:
        """Release any held resources."""


# ---------------------------------------------------------------------------
# In-memory (tests)
# ---------------------------------------------------------------------------


class InMemoryEventStore:
    """
    Non-durable in-memory store for tests.
    Exposes `.events` for direct assertions without touching a DB.
    """

    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    async def append(self, envelope: EventEnvelope) -> None:
        self.events.append(envelope)

    async def recent(
        self,
        event_types: list[str],
        limit: int = 200,
        payload_type: list[str] | None = None,
    ) -> list[EventEnvelope]:
        matching = [
            e
            for e in self.events
            if e.event_type in event_types
            and (payload_type is None or e.payload.get("type") in payload_type)
        ]
        return matching[-limit:]

    async def range(
        self,
        event_types: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[EventEnvelope]:
        matching = [
            e
            for e in self.events
            if e.event_type in event_types
            and (start is None or e.event_time >= start)
            and (end is None or e.event_time <= end)
        ]
        return sorted(matching, key=lambda e: e.event_time)

    async def prune(self, event_types: list[str], before: datetime) -> int:
        before_count = len(self.events)
        self.events = [
            e for e in self.events
            if not (e.event_type in event_types and e.event_time < before)
        ]
        return before_count - len(self.events)

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# SQLite (local dev + early production)
# ---------------------------------------------------------------------------


class SqliteEventStore:
    """
    Durable append-only store backed by the `events` table
    (see core/db/migrations/001_create_events.sql).

    INSERT OR IGNORE provides idempotency: replaying an event with an
    already-persisted id is safe and silent.
    """

    _INSERT = """
        INSERT OR IGNORE INTO events (
            id, event_type, source, schema_version,
            event_time, ingest_time, correlation_id, payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def append(self, envelope: EventEnvelope) -> None:
        # model_dump(mode="json") converts UUIDs → str, datetimes → ISO strings,
        # Decimals → str — everything becomes natively JSON-serialisable.
        data = envelope.model_dump(mode="json")

        await self._conn.execute(
            self._INSERT,
            (
                data["id"],
                data["event_type"],
                data["source"],
                data["schema_version"],
                data["event_time"],
                data["ingest_time"],
                data["correlation_id"],
                json.dumps(data["payload"]),
            ),
        )
        await self._conn.commit()

        logger.debug(
            "bus.event_persisted",
            event_id=data["id"],
            event_type=data["event_type"],
        )

    async def recent(
        self,
        event_types: list[str],
        limit: int = 200,
        payload_type: list[str] | None = None,
    ) -> list[EventEnvelope]:
        """
        The most-recently-*ingested* `limit` events of the given types, in
        chronological order. `payload_type`, when given, further restricts to
        events whose payload `type` is in the list — used to give sparse signal
        subtypes (alt-data) their own backfill window so high-volume news can't
        crowd them out of the shared limit.

        Used by the gateway to rehydrate UI panels on page load — clients
        replay these through the same reducers that handle live WS events.
        Ordered by ingest_time (arrival), not event_time: this is a display /
        ops view of "what arrived recently" (two-clock rule), so alt-data whose
        event_time is the disclosure date (a 10-K filed months ago, a 30–45-day-
        stale congressional report) still surfaces instead of being pinned below
        a wall of fresh news. Backtests use range(), which orders by event_time.
        """
        if not event_types:
            return []

        placeholders = ", ".join("?" * len(event_types))
        clauses = [f"event_type IN ({placeholders})"]
        params: list[str | int] = list(event_types)
        if payload_type:
            type_ph = ", ".join("?" * len(payload_type))
            clauses.append(f"json_extract(payload, '$.type') IN ({type_ph})")
            params.extend(payload_type)
        params.append(limit)
        cursor = await self._conn.execute(
            f"""
            SELECT id, event_type, source, schema_version,
                   event_time, ingest_time, correlation_id, payload
            FROM events
            WHERE {" AND ".join(clauses)}
            ORDER BY ingest_time DESC
            LIMIT ?
            """,
            params,
        )
        rows = await cursor.fetchall()
        await cursor.close()

        envelopes = [
            EventEnvelope(
                id=row[0],
                event_type=row[1],
                source=row[2],
                schema_version=row[3],
                event_time=row[4],
                ingest_time=row[5],
                correlation_id=row[6],
                payload=json.loads(row[7]),
            )
            for row in rows
        ]
        envelopes.reverse()  # DESC query → chronological for replay
        return envelopes

    async def range(
        self,
        event_types: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[EventEnvelope]:
        """
        All events of the given types within [start, end], in chronological
        order. Used by the backtest engine to load source events for replay.
        Bounds compare against `event_time` (the financial clock).
        """
        if not event_types:
            return []

        # Stored event_time strings come from pydantic's JSON serializer,
        # which renders UTC as "…Z"; bounds must use the same form for the
        # lexicographic comparison (and index) to be correct.
        def _ts(ts: datetime) -> str:
            return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")

        placeholders = ", ".join("?" * len(event_types))
        clauses = [f"event_type IN ({placeholders})"]
        params: list[str] = list(event_types)
        if start is not None:
            clauses.append("event_time >= ?")
            params.append(_ts(start))
        if end is not None:
            clauses.append("event_time <= ?")
            params.append(_ts(end))

        cursor = await self._conn.execute(
            f"""
            SELECT id, event_type, source, schema_version,
                   event_time, ingest_time, correlation_id, payload
            FROM events
            WHERE {" AND ".join(clauses)}
            ORDER BY event_time ASC
            """,
            params,
        )
        rows = await cursor.fetchall()
        await cursor.close()

        return [
            EventEnvelope(
                id=row[0],
                event_type=row[1],
                source=row[2],
                schema_version=row[3],
                event_time=row[4],
                ingest_time=row[5],
                correlation_id=row[6],
                payload=json.loads(row[7]),
            )
            for row in rows
        ]

    async def prune(self, event_types: list[str], before: datetime) -> int:
        """Delete events older than `before` for the given types. Returns rows deleted."""
        if not event_types:
            return 0
        placeholders = ", ".join("?" * len(event_types))
        before_ts = before.astimezone(UTC).isoformat().replace("+00:00", "Z")
        cursor = await self._conn.execute(
            f"DELETE FROM events WHERE event_type IN ({placeholders}) AND event_time < ?",
            (*event_types, before_ts),
        )
        await self._conn.commit()
        deleted = cursor.rowcount
        logger.info("event_store.pruned", event_types=event_types, deleted=deleted)
        return deleted

    async def close(self) -> None:
        await self._conn.close()
