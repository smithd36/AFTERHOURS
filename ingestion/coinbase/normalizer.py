"""
CoinbaseNormalizer — converts raw Coinbase Advanced Trade WebSocket messages
into EventEnvelopes ready for the bus.

Stateless and pure: no I/O, no side effects. One instance can be reused
across many messages. All business logic for interpreting Coinbase wire
format lives here so the feed itself stays thin and the normalizer is
fully testable without a WebSocket.

Supported channels:
  ticker        → MARKET_TICK envelopes (one per product per message)
  subscriptions → empty list (logged as confirmation)
  error         → empty list (logged as error)
  <other>       → empty list (logged as debug)

Coinbase timestamp quirk: the API sends nanosecond-precision timestamps
("2026-06-09T18:00:00.123456789Z") which Python's datetime can't parse.
_parse_ts() truncates to microseconds before parsing.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import structlog

from core.schemas import EventEnvelope, EventType

logger = structlog.get_logger(__name__)

# Coinbase sends up to nanosecond precision; datetime supports only microseconds.
# This pattern captures the first 6 decimal digits and discards the rest.
_SUBSECOND_TRIM = re.compile(r"(\.\d{6})\d+")


def _parse_ts(ts: str) -> datetime:
    """Parse a Coinbase timestamp string to a UTC-aware datetime."""
    ts = _SUBSECOND_TRIM.sub(r"\1", ts)
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


class CoinbaseNormalizer:
    """
    Maps Coinbase wire messages → list[EventEnvelope].
    Returns an empty list for messages that produce no bus events.
    Never raises; malformed messages are logged and skipped.
    """

    def normalize(self, msg: dict[str, Any]) -> list[EventEnvelope]:
        channel: str = msg.get("channel", "")

        match channel:
            case "ticker":
                return self._handle_ticker(msg)
            case "subscriptions":
                logger.debug("feed.subscribed", channel="ticker", events=msg.get("events"))
                return []
            case "error":
                logger.error(
                    "feed.coinbase_error",
                    message=msg.get("message"),
                    preview=msg.get("events"),
                )
                return []
            case _:
                if channel:
                    logger.debug("feed.unhandled_channel", channel=channel)
                return []

    # ------------------------------------------------------------------
    # Channel handlers
    # ------------------------------------------------------------------

    def _handle_ticker(self, msg: dict[str, Any]) -> list[EventEnvelope]:
        ts_str: str = msg.get("timestamp", "")
        try:
            event_time = _parse_ts(ts_str) if ts_str else datetime.now(UTC)
        except (ValueError, TypeError):
            logger.warning("feed.bad_timestamp", raw_ts=ts_str)
            event_time = datetime.now(UTC)

        ingest_time = datetime.now(UTC)
        envelopes: list[EventEnvelope] = []

        for event in msg.get("events", []):
            for raw_ticker in event.get("tickers", []):
                env = self._ticker_to_envelope(raw_ticker, event_time, ingest_time, ts_str)
                if env is not None:
                    envelopes.append(env)

        return envelopes

    def _ticker_to_envelope(
        self,
        ticker: dict[str, Any],
        event_time: datetime,
        ingest_time: datetime,
        venue_ts_str: str,
    ) -> EventEnvelope | None:
        product_id: str | None = ticker.get("product_id")
        if not product_id:
            logger.warning("feed.ticker_missing_product_id", ticker=ticker)
            return None

        # All numeric fields kept as strings — preserves Decimal precision
        # for downstream consumers. None values are excluded from payload.
        payload: dict[str, Any] = {
            k: v
            for k, v in {
                "instrument": product_id,
                "venue": "coinbase",
                "price": ticker.get("price"),
                "best_bid": ticker.get("best_bid"),
                "best_ask": ticker.get("best_ask"),
                "best_bid_quantity": ticker.get("best_bid_quantity"),
                "best_ask_quantity": ticker.get("best_ask_quantity"),
                "volume_24h": ticker.get("volume_24_h"),
                "low_24h": ticker.get("low_24_h"),
                "high_24h": ticker.get("high_24_h"),
                "price_change_pct_24h": ticker.get("price_percent_chg_24_h"),
                "venue_timestamp": venue_ts_str or None,
            }.items()
            if v is not None
        }

        return EventEnvelope(
            event_type=EventType.MARKET_TICK,
            source="coinbase_ws",
            event_time=event_time,
            ingest_time=ingest_time,
            payload=payload,
        )
