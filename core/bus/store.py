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

    async def close(self) -> None:
        await self._conn.close()
