"""
Minimal SQL migration runner for SQLite.

Reads .sql files from core/db/migrations/ in lexicographic order and
applies any that haven't run yet, tracked in a `schema_migrations` table
created on first run.

Usage:
    conn = await open_db()
    await migrate(conn)
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_CREATE_TRACKING_TABLE = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        filename   TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
"""


async def migrate(conn: aiosqlite.Connection) -> None:
    """Apply all pending migrations in lexicographic order."""
    await conn.execute(_CREATE_TRACKING_TABLE)
    await conn.commit()

    async with conn.execute(
        "SELECT filename FROM schema_migrations ORDER BY filename"
    ) as cur:
        rows = await cur.fetchall()

    applied = {row[0] for row in rows}

    pending = sorted(
        path for path in MIGRATIONS_DIR.glob("*.sql") if path.name not in applied
    )

    if not pending:
        logger.info("db.migrations.up_to_date")
        return

    for path in pending:
        sql = path.read_text(encoding="utf-8")
        logger.info("db.migration.applying", filename=path.name)
        # executescript issues an implicit COMMIT before running, which is
        # fine here — DDL statements don't need to be in the same transaction
        # as the tracking INSERT.
        await conn.executescript(sql)
        await conn.execute(
            "INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,)
        )
        await conn.commit()
        logger.info("db.migration.applied", filename=path.name)
