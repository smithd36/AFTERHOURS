"""
EquityFeed — REST polling stub for equity market data.

Polls the configured provider every `poll_interval_seconds` for each
watched symbol and emits the same market.tick envelope as KrakenFeed.

Supported providers (free tier, delayed data):
  alpaca  — Alpaca Data API v2, IEX feed (requires free API key)
  polygon — Polygon.io v2 last trade (requires free API key)

No-op mode: if `api_key` is empty or provider is "none", the feed logs
a warning and runs an idle loop.  Subscriptions still work correctly so
the watchlist and FeedRouter behave normally without credentials.

Upgrading to a WS-based provider in Phase 7 is a drop-in: the
subscribe()/unsubscribe() interface and market.tick envelope are stable.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import structlog

from core.bus.base import Bus
from core.schemas.events import EventEnvelope, EventType

from .settings import EquityFeedSettings

logger = structlog.get_logger(__name__)

_ALPACA_SNAPSHOT_URL = "https://data.alpaca.markets/v2/stocks/snapshots"
_POLYGON_LAST_TRADE_URL = "https://api.polygon.io/v2/last/trade/{symbol}"


class EquityFeed:
    """REST polling equity feed.  subscribe()/unsubscribe() are thread-safe."""

    def __init__(self, bus: Bus, settings: EquityFeedSettings | None = None) -> None:
        self._bus = bus
        self._settings = settings or EquityFeedSettings()
        self._instruments: set[str] = set()

    async def subscribe(self, instrument: str) -> None:
        self._instruments.add(instrument)
        logger.info("equity_feed.subscribed", instrument=instrument)

    async def unsubscribe(self, instrument: str) -> None:
        self._instruments.discard(instrument)
        logger.info("equity_feed.unsubscribed", instrument=instrument)

    async def run(self) -> None:
        if not self._settings.api_key or self._settings.provider == "none":
            logger.warning(
                "equity_feed.no_op",
                reason="EQUITY_FEED_API_KEY not set or provider=none; "
                       "subscriptions tracked but no ticks emitted",
            )
            while True:
                await asyncio.sleep(3600)

        logger.info("equity_feed.starting", provider=self._settings.provider)
        while True:
            await asyncio.sleep(self._settings.poll_interval_seconds)
            if self._instruments:
                await self._poll()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _poll(self) -> None:
        symbols = list(self._instruments)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if self._settings.provider == "alpaca":
                    await self._poll_alpaca(client, symbols)
                elif self._settings.provider == "polygon":
                    await self._poll_polygon(client, symbols)
                else:
                    logger.warning("equity_feed.unknown_provider", provider=self._settings.provider)
        except Exception as exc:
            logger.warning("equity_feed.poll_error", error=str(exc))

    async def _poll_alpaca(self, client: httpx.AsyncClient, symbols: list[str]) -> None:
        resp = await client.get(
            _ALPACA_SNAPSHOT_URL,
            params={"symbols": ",".join(symbols), "feed": "iex"},
            headers={
                "APCA-API-KEY-ID": self._settings.api_key,
                "APCA-API-SECRET-KEY": self._settings.api_secret,
            },
        )
        resp.raise_for_status()
        now = datetime.now(UTC)
        for symbol, snapshot in resp.json().items():
            price = (snapshot.get("latestTrade") or {}).get("p")
            if price is not None:
                await self._emit_tick(symbol, str(price), "alpaca", now)

    async def _poll_polygon(self, client: httpx.AsyncClient, symbols: list[str]) -> None:
        now = datetime.now(UTC)
        for symbol in symbols:
            resp = await client.get(
                _POLYGON_LAST_TRADE_URL.format(symbol=symbol),
                params={"apiKey": self._settings.api_key},
            )
            resp.raise_for_status()
            price = (resp.json().get("results") or {}).get("p")
            if price is not None:
                await self._emit_tick(symbol, str(price), "polygon", now)

    async def _emit_tick(
        self, instrument: str, price: str, venue: str, now: datetime
    ) -> None:
        await self._bus.publish(EventEnvelope(
            event_type=EventType.MARKET_TICK,
            source="equity_feed",
            event_time=now,
            ingest_time=now,
            payload={"instrument": instrument, "venue": venue, "price": price},
        ))
