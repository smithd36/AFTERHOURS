"""
TickPruner — background task that deletes old market.tick events.

Runs every `prune_interval_hours` and deletes ticks older than
`retention_days` from the event store.  Keeps SQLite growth bounded
regardless of watchlist size.

Disabled in tests by setting retention_days=0 or not starting it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.bus.store import SqliteEventStore
from core.schemas.events import EventType

logger = structlog.get_logger(__name__)


class PrunerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    retention_days: int = Field(default=30, alias="TICK_RETENTION_DAYS")
    prune_interval_hours: int = Field(default=24, alias="TICK_PRUNE_INTERVAL_HOURS")


class TickPruner:
    def __init__(
        self,
        store: SqliteEventStore,
        settings: PrunerSettings | None = None,
    ) -> None:
        self._store = store
        self._settings = settings or PrunerSettings()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="tick_pruner")
        logger.info(
            "tick_pruner.started",
            retention_days=self._settings.retention_days,
            interval_hours=self._settings.prune_interval_hours,
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("tick_pruner.stopped")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._settings.prune_interval_hours * 3600)
            await self._prune()

    async def _prune(self) -> None:
        before = datetime.now(UTC) - timedelta(days=self._settings.retention_days)
        deleted = await self._store.prune([EventType.MARKET_TICK.value], before)
        logger.info("tick_pruner.pruned", deleted=deleted, before=before.isoformat())
