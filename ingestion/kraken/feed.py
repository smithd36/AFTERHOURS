"""
KrakenFeed — Kraken WebSocket v2 market-data feed.

Connects to wss://ws.kraken.com/v2 (no auth required for public data),
subscribes to the ticker channel, and publishes MARKET_TICK events to the bus.

Dynamic subscriptions: call subscribe(instrument) / unsubscribe(instrument)
at any time.  If a connection is live the message is sent immediately; if
the feed is reconnecting the updated instrument set is used on the next
_subscribe() call.

Kraken v2 subscribe message:
    {"method": "subscribe", "params": {"channel": "ticker", "symbol": [...]}}

Subscription confirmation:
    {"method": "subscribe", "success": true, "result": {"channel": "ticker", ...}}

Ticker update:
    {"channel": "ticker", "type": "update", "data": [{symbol, last, bid, ask, ...}]}
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import structlog
import websockets
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_never,
    wait_exponential,
)

from core.bus import Bus
from core.schemas import EventEnvelope, EventType

from .normalizer import KrakenNormalizer, canonical_to_kraken
from .settings import KrakenFeedSettings

logger = structlog.get_logger(__name__)


class KrakenFeed:
    """
    Subscribes to the Kraken v2 WebSocket ticker channel (no auth required)
    and publishes MARKET_TICK and system health events to the bus.

    `_active_instruments` is the live set of canonical symbols (e.g. "BTC-USD").
    It starts from settings.products and is updated by subscribe()/unsubscribe().
    On reconnect, _subscribe() uses the current set — no instruments are lost.
    """

    def __init__(self, bus: Bus, settings: KrakenFeedSettings | None = None) -> None:
        self._bus = bus
        self._settings = settings or KrakenFeedSettings()
        self._normalizer = KrakenNormalizer()
        self._active_instruments: set[str] = set(self._settings.products)
        self._ws: Any = None  # current live WS connection; None when disconnected

    # ------------------------------------------------------------------
    # Dynamic subscription management (Phase 5)
    # ------------------------------------------------------------------

    async def subscribe(self, instrument: str) -> None:
        """Add an instrument. Sends WS message immediately if connected."""
        if instrument in self._active_instruments:
            return
        self._active_instruments.add(instrument)
        if self._ws is not None:
            await self._send_sub_message("subscribe", [instrument])
        logger.info("kraken_feed.subscribed", instrument=instrument)

    async def unsubscribe(self, instrument: str) -> None:
        """Remove an instrument. Sends WS message immediately if connected."""
        self._active_instruments.discard(instrument)
        if self._ws is not None:
            await self._send_sub_message("unsubscribe", [instrument])
        logger.info("kraken_feed.unsubscribed", instrument=instrument)

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run forever, reconnecting with exponential backoff on any disconnect."""
        logger.info("kraken_feed.starting", instruments=list(self._active_instruments))
        async for attempt in AsyncRetrying(
            wait=wait_exponential(multiplier=1, min=1, max=60),
            stop=stop_never,
            retry=retry_if_exception_type(Exception),
            before_sleep=before_sleep_log(logger, logging.WARNING),
        ):
            with attempt:
                await self._stream()

    async def close(self) -> None:
        logger.info("kraken_feed.closing")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _stream(self) -> None:
        """One connection lifetime. Raises on any error so tenacity can retry."""
        logger.info("kraken_feed.connecting", url=self._settings.ws_url)
        async with websockets.connect(  # type: ignore[attr-defined]
            self._settings.ws_url,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:
            self._ws = ws
            await self._subscribe(ws)
            logger.info("kraken_feed.connected", instruments=list(self._active_instruments))

            async for raw in ws:
                await self._dispatch(raw)

        self._ws = None
        raise ConnectionResetError("Kraken WS closed cleanly — reconnecting")

    async def _subscribe(self, ws: Any) -> None:
        """Subscribe to all currently active instruments on a fresh connection."""
        if not self._active_instruments:
            return
        kraken_symbols = [canonical_to_kraken(p) for p in self._active_instruments]
        await self._send_sub_message_on_ws(ws, "subscribe", kraken_symbols)

    async def _send_sub_message(self, method: str, instruments: list[str]) -> None:
        """Send a subscribe/unsubscribe on the live connection (no-op if disconnected)."""
        if self._ws is None:
            return
        await self._send_sub_message_on_ws(
            self._ws, method, [canonical_to_kraken(i) for i in instruments]
        )

    @staticmethod
    async def _send_sub_message_on_ws(ws: Any, method: str, kraken_symbols: list[str]) -> None:
        await ws.send(json.dumps({
            "method": method,
            "params": {"channel": "ticker", "symbol": kraken_symbols},
        }))

    async def _dispatch(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("kraken_feed.parse_error", preview=str(raw)[:200])
            return

        # Subscription confirmation: {"method": "subscribe", "success": true, ...}
        if msg.get("method") in ("subscribe", "unsubscribe"):
            if msg.get("success") is True:
                await self._publish_system(EventType.SYSTEM_FEED_HEALTHY)
            else:
                logger.error(
                    "kraken_feed.subscribe_failed",
                    error=msg.get("error"),
                    result=msg.get("result"),
                )
            return

        envelopes = self._normalizer.normalize(msg)
        for env in envelopes:
            await self._bus.publish(env)

    async def _publish_system(self, event_type: str, **extra: Any) -> None:
        now = datetime.now(UTC)
        await self._bus.publish(
            EventEnvelope(
                event_type=event_type,
                source="kraken_ws",
                event_time=now,
                ingest_time=now,
                payload={"feed_id": "kraken_ws", **extra},
            )
        )
