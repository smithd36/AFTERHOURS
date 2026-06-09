"""
KrakenNormalizer — converts Kraken WebSocket v2 messages into EventEnvelopes.

Key differences from Coinbase:
  - Symbol format: "BTC/USD" (Kraken) ↔ "BTC-USD" (canonical)
  - Kraken v2 also uses "XBT/USD" as an alias for Bitcoin — normalised to BTC-USD.
  - All numeric fields arrive as floats; we stringify them for Decimal safety.
  - Ticker items carry no item-level timestamp; event_time == ingest_time.
  - Subscription confirmations carry a top-level "method" key, not "channel".

Supported message shapes:
  {"channel": "ticker", "type": "update"|"snapshot", "data": [...]}  → MARKET_TICK
  {"channel": "heartbeat", ...}                                       → []
  {"channel": "status",    ...}                                       → []
  {"method": "subscribe",  "success": true, ...}                      → []  (handled in feed)
  <anything else>                                                      → []
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from core.schemas import EventEnvelope, EventType

logger = structlog.get_logger(__name__)


def kraken_to_canonical(symbol: str) -> str:
    """'BTC/USD' → 'BTC-USD'.  Handles Kraken's XBT alias for Bitcoin."""
    return symbol.replace("XBT/", "BTC/").replace("/", "-")


def canonical_to_kraken(symbol: str) -> str:
    """'BTC-USD' → 'BTC/USD' for use in subscribe payloads."""
    return symbol.replace("-", "/")


class KrakenNormalizer:
    """
    Maps Kraken v2 wire messages → list[EventEnvelope].
    Returns an empty list for messages that produce no bus events.
    Never raises; malformed items are logged and skipped.
    """

    def normalize(self, msg: dict[str, Any]) -> list[EventEnvelope]:
        channel: str = msg.get("channel", "")

        match channel:
            case "ticker":
                msg_type: str = msg.get("type", "")
                if msg_type in ("update", "snapshot"):
                    return self._handle_ticker(msg)
                return []
            case "heartbeat" | "status":
                return []
            case _:
                if channel:
                    logger.debug("kraken_feed.unhandled_channel", channel=channel)
                return []

    # ------------------------------------------------------------------
    # Channel handlers
    # ------------------------------------------------------------------

    def _handle_ticker(self, msg: dict[str, Any]) -> list[EventEnvelope]:
        # Kraken v2 ticker items carry no item-level timestamp.
        # event_time == ingest_time is a known limitation for this feed.
        now = datetime.now(UTC)
        envelopes: list[EventEnvelope] = []
        for item in msg.get("data", []):
            env = self._item_to_envelope(item, now)
            if env is not None:
                envelopes.append(env)
        return envelopes

    def _item_to_envelope(
        self, item: dict[str, Any], now: datetime
    ) -> EventEnvelope | None:
        symbol: str = item.get("symbol", "")
        last = item.get("last")
        if not symbol or last is None:
            logger.warning("kraken_feed.ticker_missing_field", item=item)
            return None

        payload: dict[str, str] = {
            "instrument": kraken_to_canonical(symbol),
            "venue": "kraken",
            "price": str(last),
        }

        # Optional fields — only include when present to match Coinbase normalizer style.
        optional: dict[str, Any] = {
            "best_bid": item.get("bid"),
            "best_ask": item.get("ask"),
            "best_bid_quantity": item.get("bid_qty"),
            "best_ask_quantity": item.get("ask_qty"),
            "volume_24h": item.get("volume"),
            "low_24h": item.get("low"),
            "high_24h": item.get("high"),
            "price_change_pct_24h": item.get("change_pct"),
        }
        for key, val in optional.items():
            if val is not None:
                payload[key] = str(val)

        return EventEnvelope(
            event_type=EventType.MARKET_TICK,
            source="kraken_ws",
            event_time=now,
            ingest_time=now,
            payload=payload,
        )
