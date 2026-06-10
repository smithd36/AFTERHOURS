CREATE TABLE IF NOT EXISTS watchlist (
    instrument  TEXT PRIMARY KEY,
    market      TEXT NOT NULL DEFAULT 'crypto',  -- 'crypto' | 'equity'
    added_at    TEXT NOT NULL,                   -- ISO-8601 UTC
    enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS watchlist_enabled ON watchlist (enabled);
