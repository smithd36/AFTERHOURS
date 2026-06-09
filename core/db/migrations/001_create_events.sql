-- Append-only event store. The audit log IS this table.
-- Never UPDATE or DELETE rows. Corrections are new events.
--
-- Types: SQLite has no native UUID or timestamptz types.
--   id, correlation_id  → TEXT (UUID string)
--   event_time, ingest_time → TEXT (ISO-8601 UTC, e.g. "2026-06-09T14:32:00.000000+00:00")
--   payload             → TEXT (JSON string)
--
-- Two-clock invariant (see ADR-001):
--   event_time  = when the domain event occurred (market/source clock)
--   ingest_time = when we published onto the bus (our clock)
--   ALL financial logic must use event_time. Never use ingest_time for financial logic.
--
-- Indexes are sized for Phase 0–3 query patterns:
--   replay a time range            → idx_events_event_time
--   filter by type + time          → idx_events_type_time
--   reconstruct a Decision lifecycle → idx_events_correlation_id

CREATE TABLE IF NOT EXISTS events (
    id               TEXT NOT NULL PRIMARY KEY,
    event_type       TEXT NOT NULL,
    source           TEXT NOT NULL,
    schema_version   TEXT NOT NULL DEFAULT '1.0',
    event_time       TEXT NOT NULL,
    ingest_time      TEXT NOT NULL,
    correlation_id   TEXT,
    payload          TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_events_event_time
    ON events (event_time DESC);

CREATE INDEX IF NOT EXISTS idx_events_type_time
    ON events (event_type, event_time DESC);

CREATE INDEX IF NOT EXISTS idx_events_correlation_id
    ON events (correlation_id)
    WHERE correlation_id IS NOT NULL;
