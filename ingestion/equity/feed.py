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
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog

from core.bus.base import Bus
from core.market_hours import is_equity_market_open
from core.schemas.events import EventEnvelope, EventType

from .settings import EquityFeedSettings

logger = structlog.get_logger(__name__)

_EASTERN = ZoneInfo("America/New_York")


def _is_market_open() -> bool:
    # One definition of NYSE regular hours lives in core.market_hours; the risk
    # engine and executor gate on the same logic (keyed on event_time) so the
    # feed, entries, and closes all agree on when the equity venue is open.
    return is_equity_market_open(datetime.now(UTC))


def _seconds_until_open() -> float:
    """Seconds until the next NYSE open (9:30 ET on a weekday)."""
    now_et = datetime.now(_EASTERN)
    candidate = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    if candidate <= now_et:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return (candidate - now_et).total_seconds()


_ALPACA_SNAPSHOT_URL = "https://data.alpaca.markets/v2/stocks/snapshots"
_POLYGON_LAST_TRADE_URL = "https://api.polygon.io/v2/last/trade/{symbol}"


def alpaca_snapshot_to_payload(snapshot: dict[str, Any]) -> dict[str, str] | None:
    """
    Map one symbol's Alpaca snapshot to the optional market.tick payload
    fields (same keys as the Kraken normalizer).  Returns None when the
    snapshot has no last trade price.

    For equities, `price_change_pct_24h` is the change vs. the previous
    session's close — the standard day-% convention — not a literal 24h
    window.  IEX reports a bid/ask of 0 when that side of the book is
    empty (e.g. outside market hours), so zeros are omitted.
    """
    price = (snapshot.get("latestTrade") or {}).get("p")
    if price is None:
        return None

    payload: dict[str, str] = {"price": str(price)}

    quote = snapshot.get("latestQuote") or {}
    if quote.get("bp"):
        payload["best_bid"] = str(quote["bp"])
    if quote.get("ap"):
        payload["best_ask"] = str(quote["ap"])

    daily = snapshot.get("dailyBar") or {}
    optional = {
        "high_24h": daily.get("h"),
        "low_24h": daily.get("l"),
        "volume_24h": daily.get("v"),
    }
    for key, val in optional.items():
        if val is not None:
            payload[key] = str(val)

    prev_close = (snapshot.get("prevDailyBar") or {}).get("c")
    if prev_close:
        try:
            change = (Decimal(str(price)) / Decimal(str(prev_close)) - 1) * 100
            payload["price_change_pct_24h"] = str(round(change, 2))
        except (InvalidOperation, ZeroDivisionError):
            pass

    return payload


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
            if not _is_market_open():
                secs = _seconds_until_open()
                logger.info("equity_feed.market_closed", next_open_seconds=round(secs))
                await asyncio.sleep(secs)
                continue
            if self._instruments:
                await self._poll()
            await asyncio.sleep(self._settings.poll_interval_seconds)

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
            payload = alpaca_snapshot_to_payload(snapshot)
            if payload is None:
                continue
            # Use venue trade timestamp as event_time (two-clock rule).
            # Fall back to ingest wall-clock only when the field is absent.
            trade_ts_raw = (snapshot.get("latestTrade") or {}).get("t")
            try:
                event_time = datetime.fromisoformat(trade_ts_raw) if trade_ts_raw else now
            except (ValueError, TypeError):
                event_time = now
            await self._emit_tick(symbol, "alpaca", event_time, payload)

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
                await self._emit_tick(symbol, "polygon", now, {"price": str(price)})

    async def _emit_tick(
        self, instrument: str, venue: str, now: datetime, payload: dict[str, str]
    ) -> None:
        await self._bus.publish(EventEnvelope(
            event_type=EventType.MARKET_TICK,
            source="equity_feed",
            event_time=now,
            ingest_time=now,
            payload={"instrument": instrument, "venue": venue, **payload},
        ))
