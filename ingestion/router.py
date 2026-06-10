"""
FeedRouter — maps watchlist changes to feed adapter subscriptions.

When an instrument is added to the watchlist, FeedRouter routes it to
the correct feed adapter (KrakenFeed for crypto, EquityFeed for equity).
On removal it unsubscribes from the same adapter.

Bootstrap: start() subscribes all currently active instruments so the
router stays consistent with a pre-populated watchlist on restart.
"""

from __future__ import annotations

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.events import EventEnvelope, EventType
from ingestion.equity.feed import EquityFeed
from ingestion.kraken.feed import KrakenFeed
from watchlist.manager import WatchlistManager

logger = structlog.get_logger(__name__)


class FeedRouter:
    def __init__(
        self,
        bus: Bus,
        watchlist_manager: WatchlistManager,
        kraken_feed: KrakenFeed,
        equity_feed: EquityFeed | None = None,
    ) -> None:
        self._bus = bus
        self._watchlist = watchlist_manager
        self._kraken = kraken_feed
        self._equity = equity_feed
        self._subs: list[Subscription] = []

    async def start(self) -> None:
        # Subscribe all currently active instruments.
        for instrument in self._watchlist.active_instruments:
            market = self._watchlist.get_market(instrument)
            await self._route_subscribe(instrument, market)

        # Listen for future watchlist changes.
        self._subs.append(
            await self._bus.subscribe(
                EventType.WATCHLIST_INSTRUMENT_ADDED, self._handle_added
            )
        )
        self._subs.append(
            await self._bus.subscribe(
                EventType.WATCHLIST_INSTRUMENT_REMOVED, self._handle_removed
            )
        )
        logger.info("feed_router.started")

    async def stop(self) -> None:
        for sub in self._subs:
            await self._bus.unsubscribe(sub)
        self._subs.clear()
        logger.info("feed_router.stopped")

    # ------------------------------------------------------------------
    # Bus handlers
    # ------------------------------------------------------------------

    async def _handle_added(self, envelope: EventEnvelope) -> None:
        instrument: str = envelope.payload.get("instrument", "")
        market: str = envelope.payload.get("market", "crypto")
        if instrument:
            await self._route_subscribe(instrument, market)

    async def _handle_removed(self, envelope: EventEnvelope) -> None:
        instrument: str = envelope.payload.get("instrument", "")
        market: str = envelope.payload.get("market", "crypto")
        if instrument:
            await self._route_unsubscribe(instrument, market)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    async def _route_subscribe(self, instrument: str, market: str) -> None:
        if market == "equity":
            if self._equity is not None:
                await self._equity.subscribe(instrument)
            else:
                logger.warning(
                    "feed_router.no_equity_feed", instrument=instrument
                )
        else:
            await self._kraken.subscribe(instrument)

    async def _route_unsubscribe(self, instrument: str, market: str) -> None:
        if market == "equity":
            if self._equity is not None:
                await self._equity.unsubscribe(instrument)
        else:
            await self._kraken.unsubscribe(instrument)
