# ADR-002: SQLite for Local Event Storage

**Status:** Accepted
**Date:** 2026-06-09
**Deciders:** @smithd36

---

## Context

Every event published to the bus must be persisted before fan-out (see ADR-001). The storage layer must:

1. **Be append-only** — events are immutable once written. No updates, no deletes.
2. **Support concurrent reads during writes** — the gateway WebSocket handler reads recent events while the ingestion feed is writing new ones continuously.
3. **Require zero ops overhead in Phase 0** — no separate database process, no connection pooling config, no cluster to manage.
4. **Support the two-clock invariant** — `event_time` (source clock) and `ingest_time` (our clock) must both be stored as-is without coercion.
5. **Have a clear upgrade path** — when Phase 4 (live execution) demands higher write throughput or multi-host access, we need to be able to swap the store without changing the `EventStore` protocol.

---

## Decision

**Use SQLite with WAL mode as the local event store.**

### Schema

```sql
CREATE TABLE events (
    id             TEXT PRIMARY KEY,
    event_type     TEXT NOT NULL,
    source         TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    event_time     TEXT NOT NULL,    -- ISO-8601 UTC string (source/venue clock)
    ingest_time    TEXT NOT NULL,    -- ISO-8601 UTC string (our clock)
    correlation_id TEXT,
    payload        TEXT NOT NULL     -- JSON blob
) STRICT;
```

All monetary values and timestamps are stored as TEXT to preserve Decimal precision and avoid SQLite's lossy REAL type. Pydantic serialises them with `model_dump(mode="json")` which renders `Decimal` as string and `datetime` as ISO-8601.

### WAL mode

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
```

WAL (Write-Ahead Logging) allows concurrent readers during a write transaction. Without it, a write locks the file and blocks all readers until the commit completes — unacceptable for the WebSocket gateway which reads recent events while the feed writes continuously. `PRAGMA synchronous = NORMAL` retains crash safety for most scenarios while avoiding the performance cost of `FULL`.

### Idempotency

Inserts use `INSERT OR IGNORE` keyed on `id` (UUID). Re-publishing the same envelope (e.g., during a replay or reconnect) silently skips duplicates.

### Indexes

Three partial / composite indexes cover the expected query patterns:

```sql
CREATE INDEX idx_events_event_time      ON events(event_time DESC);
CREATE INDEX idx_events_type_time       ON events(event_type, event_time DESC);
CREATE INDEX idx_events_correlation_id  ON events(correlation_id) WHERE correlation_id IS NOT NULL;
```

### EventStore protocol

The application never references `SqliteEventStore` directly. It depends on the `EventStore` protocol:

```python
class EventStore(Protocol, runtime_checkable):
    async def append(self, envelope: EventEnvelope) -> None: ...
```

Tests use `InMemoryEventStore`. Production uses `SqliteEventStore`. The `InProcessBus` receives an `EventStore` instance at construction; it does not know or care which implementation it has.

---

## Consequences

### Positive
- Zero external dependencies — just aiosqlite wrapping the stdlib sqlite3.
- WAL mode makes readers and writers non-blocking — ingestion and gateway can run concurrently without contention.
- `INSERT OR IGNORE` makes event publishing idempotent — safe to replay from reconnects.
- Full audit trail from day one — every published event is on disk.
- `EventStore` protocol means swapping to Postgres or Turso is a one-file change.

### Negative / constraints
- SQLite is single-writer — concurrent writes from multiple processes are not possible. This is acceptable for Phase 0–3 (single process). If execution isolation requires a separate process in Phase 4, the bus transport must be extracted at the same time (see ADR-001 transport table).
- No streaming queries — consumers that need recent events must poll or be delivered via the bus fan-out. There is no `LISTEN/NOTIFY` equivalent.
- TEXT timestamp storage means time-range queries require ISO-8601 string comparison (which is lexicographically correct for UTC timestamps, so this works correctly as long as the format is consistent).

---

## Alternatives Considered

### PostgreSQL from day one
Rejected. Requires a running Postgres process, connection pooling (asyncpg), and a migration tool (Alembic). Significant ops overhead before the product is proven. The `EventStore` protocol keeps the upgrade path open.

### Append to flat file (JSON Lines)
Rejected. No indexed queries; no dedup by ID; no structured reads for the calibration engine. More fragile than a proper database.

### No persistence (in-memory only)
Rejected. Violates the persist-first guarantee in ADR-001. An in-memory bus without persistence cannot provide the audit trail or replay capability the system requires.
