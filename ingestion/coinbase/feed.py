"""
CoinbaseFeed — Coinbase Advanced Trade WebSocket market-data feed.

Connects to the public ticker channel (no API key required), normalizes
messages via CoinbaseNormalizer, and publishes EventEnvelopes to the bus.

Reconnect behaviour:
  - Exponential backoff: 1s → 2s → 4s … capped at 60s.
  - Retries on any Exception (connection error, timeout, protocol error).
  - asyncio.CancelledError is NOT retried — it propagates to stop the task.

Lifecycle:
    feed = CoinbaseFeed(bus)
    task = asyncio.create_task(feed.run())   # runs until cancelled
    ...
    task.cancel()                            # graceful stop
    await task
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

from .normalizer import CoinbaseNormalizer
from .settings import CoinbaseFeedSettings

logger = structlog.get_logger(__name__)


class CoinbaseFeed:
    """
    Subscribes to the Coinbase Advanced Trade WebSocket ticker channel
    and publishes MARKET_TICK (and system health) events to the bus.
    """

    def __init__(
        self,
        bus: Bus,
        settings: CoinbaseFeedSettings | None = None,
    ) -> None:
        self._bus = bus
        self._settings = settings or CoinbaseFeedSettings()
        self._normalizer = CoinbaseNormalizer()

    async def run(self) -> None:
        """Run forever, reconnecting with exponential backoff on any disconnect."""
        logger.info("feed.starting", products=self._settings.products)
        async for attempt in AsyncRetrying(
            wait=wait_exponential(multiplier=1, min=1, max=60),
            stop=stop_never,
            # Only retry Exception subclasses — CancelledError is BaseException
            # and will propagate, stopping the task cleanly on cancellation.
            retry=retry_if_exception_type(Exception),
            before_sleep=before_sleep_log(logger, logging.WARNING),
        ):
            with attempt:
                await self._stream()

    async def close(self) -> None:
        """Cancel the owning task to stop. This method is a hook for cleanup."""
        logger.info("feed.closing")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _stream(self) -> None:
        """One connection lifetime. Raises on any error so tenacity can retry."""
        logger.info("feed.connecting", url=self._settings.ws_url)
        async with websockets.connect(  # type: ignore[attr-defined]
            self._settings.ws_url,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:
            await self._subscribe(ws)
            logger.info("feed.connected", products=self._settings.products)

            async for raw in ws:
                await self._dispatch(raw)

        # Reached only on clean close (server closed connection).
        # Raise so tenacity treats it as a disconnect and reconnects.
        raise ConnectionResetError("Coinbase WS closed cleanly — reconnecting")

    async def _subscribe(self, ws: Any) -> None:
        payload = json.dumps(
            {
                "type": "subscribe",
                "product_ids": self._settings.products,
                "channel": "ticker",
            }
        )
        await ws.send(payload)

    async def _dispatch(self, raw: str | bytes) -> None:
        """Parse one raw WebSocket message and publish any resulting envelopes."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("feed.parse_error", preview=str(raw)[:200])
            return

        # Publish system feed health on subscriptions confirmation
        if data.get("channel") == "subscriptions":
            await self._publish_system(EventType.SYSTEM_FEED_HEALTHY)

        envelopes = self._normalizer.normalize(data)
        for env in envelopes:
            await self._bus.publish(env)

    async def _publish_system(self, event_type: str, **extra: Any) -> None:
        now = datetime.now(UTC)
        await self._bus.publish(
            EventEnvelope(
                event_type=event_type,
                source="coinbase_ws",
                event_time=now,
                ingest_time=now,
                payload={"feed_id": "coinbase_ws", **extra},
            )
        )
