"""
SQLite connection factory.

Opens an aiosqlite connection with WAL mode (better read concurrency)
and sensible PRAGMAs. The caller owns the connection's lifetime and
must call conn.close() on shutdown.

Usage:
    conn = await open_db()              # reads DB_PATH from env / .env (default: afterhours.db)
    conn = await open_db(":memory:")    # in-memory DB for tests
    conn = await open_db("custom.db")  # explicit path
    ...
    await conn.close()

Upgrading to Postgres later: replace this file with a psycopg3 pool factory
and update SqliteEventStore → PostgresEventStore in core/bus/store.py.
The Bus interface and all callers stay unchanged.
"""

from __future__ import annotations

import aiosqlite
import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger(__name__)


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    db_path: str = Field(default="afterhours.db", alias="DB_PATH")


async def open_db(path: str | None = None) -> aiosqlite.Connection:
    """Open and configure an async SQLite connection."""
    settings = DatabaseSettings()
    db_path = path or settings.db_path

    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row

    # WAL mode: readers don't block writers, writers don't block readers.
    # Critical for the bus writing events while the gateway reads them.
    await conn.execute("PRAGMA journal_mode=WAL")
    # NORMAL: fsync only at checkpoints. Safe for our use case; not zero-loss on power failure.
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")

    logger.info("db.opened", path=db_path)
    return conn
