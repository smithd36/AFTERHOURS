"""
WatchlistManager — runtime instrument registry.

Loads the persisted watchlist on startup, seeds defaults on first run,
and publishes watchlist.instrument_added / watchlist.instrument_removed
onto the bus so FeedRouter and pipeline components can react immediately.

Pipeline components receive a reference and gate on `active_instruments`;
they never subscribe to the bus themselves for watchlist events.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from core.bus.base import Bus
from core.schemas.events import EventEnvelope, EventType

from .settings import WatchlistSettings
from .store import WatchlistEntry, WatchlistStore

logger = structlog.get_logger(__name__)


class WatchlistManager:
    def __init__(
        self,
        bus: Bus,
        store: WatchlistStore,
        settings: WatchlistSettings | None = None,
    ) -> None:
        self._bus = bus
        self._store = store
        self._settings = settings or WatchlistSettings()
        # instrument → market; populated in start()
        self._active: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        entries = await self._store.list_active()
        if not entries:
            for instrument in self._settings.default_instruments:
                await self._store.add(instrument, self._settings.default_market)
                logger.info("watchlist.seeded", instrument=instrument)
            entries = await self._store.list_active()

        self._active = {e.instrument: e.market for e in entries}
        logger.info("watchlist.loaded", count=len(self._active), instruments=list(self._active))

    async def stop(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @property
    def active_instruments(self) -> frozenset[str]:
        return frozenset(self._active)

    def get_market(self, instrument: str) -> str:
        return self._active.get(instrument, "crypto")

    async def list_entries(self) -> list[WatchlistEntry]:
        return await self._store.list_active()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def add(self, instrument: str, market: str = "crypto") -> None:
        await self._store.add(instrument, market)
        self._active[instrument] = market
        await self._publish(EventType.WATCHLIST_INSTRUMENT_ADDED, instrument, market)
        logger.info("watchlist.added", instrument=instrument, market=market)

    async def remove(self, instrument: str) -> None:
        market = self._active.pop(instrument, "crypto")
        await self._store.remove(instrument)
        await self._publish(EventType.WATCHLIST_INSTRUMENT_REMOVED, instrument, market)
        logger.info("watchlist.removed", instrument=instrument)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _publish(self, event_type: EventType, instrument: str, market: str) -> None:
        now = datetime.now(UTC)
        await self._bus.publish(EventEnvelope(
            event_type=event_type,
            source="watchlist_manager",
            event_time=now,
            ingest_time=now,
            payload={"instrument": instrument, "market": market},
        ))
