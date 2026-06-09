"""Tests for KrakenNormalizer and symbol conversion utilities."""

from __future__ import annotations

from typing import Any

import pytest

from core.schemas.events import EventType
from ingestion.kraken.normalizer import (
    KrakenNormalizer,
    canonical_to_kraken,
    kraken_to_canonical,
)


# ---------------------------------------------------------------------------
# Symbol conversion
# ---------------------------------------------------------------------------


class TestSymbolConversion:
    def test_kraken_to_canonical(self) -> None:
        assert kraken_to_canonical("BTC/USD") == "BTC-USD"

    def test_kraken_to_canonical_eth(self) -> None:
        assert kraken_to_canonical("ETH/USD") == "ETH-USD"

    def test_xbt_aliased_to_btc(self) -> None:
        # Kraken v1 / some v2 responses still use XBT
        assert kraken_to_canonical("XBT/USD") == "BTC-USD"

    def test_canonical_to_kraken(self) -> None:
        assert canonical_to_kraken("BTC-USD") == "BTC/USD"

    def test_canonical_to_kraken_eth(self) -> None:
        assert canonical_to_kraken("ETH-USD") == "ETH/USD"

    def test_round_trip(self) -> None:
        assert kraken_to_canonical(canonical_to_kraken("BTC-USD")) == "BTC-USD"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ticker_msg(items: list[dict[str, Any]], msg_type: str = "update") -> dict[str, Any]:
    return {"channel": "ticker", "type": msg_type, "data": items}


def _item(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "symbol": "BTC/USD",
        "last": 65000.5,
        "bid": 65000.0,
        "bid_qty": 0.5,
        "ask": 65001.0,
        "ask_qty": 0.3,
        "volume": 1234.56,
        "low": 63000.0,
        "high": 66000.0,
        "change_pct": 1.56,
    }
    base.update(kwargs)
    return base


@pytest.fixture
def normalizer() -> KrakenNormalizer:
    return KrakenNormalizer()


# ---------------------------------------------------------------------------
# Ticker update
# ---------------------------------------------------------------------------


class TestTickerUpdate:
    def test_produces_one_envelope_per_item(self, normalizer: KrakenNormalizer) -> None:
        result = normalizer.normalize(_ticker_msg([_item(), _item(symbol="ETH/USD", last=3500.0)]))
        assert len(result) == 2

    def test_event_type_is_market_tick(self, normalizer: KrakenNormalizer) -> None:
        result = normalizer.normalize(_ticker_msg([_item()]))
        assert result[0].event_type == EventType.MARKET_TICK

    def test_source_is_kraken_ws(self, normalizer: KrakenNormalizer) -> None:
        result = normalizer.normalize(_ticker_msg([_item()]))
        assert result[0].source == "kraken_ws"

    def test_instrument_is_canonical(self, normalizer: KrakenNormalizer) -> None:
        result = normalizer.normalize(_ticker_msg([_item(symbol="BTC/USD")]))
        assert result[0].payload["instrument"] == "BTC-USD"

    def test_xbt_normalised_to_btc(self, normalizer: KrakenNormalizer) -> None:
        result = normalizer.normalize(_ticker_msg([_item(symbol="XBT/USD")]))
        assert result[0].payload["instrument"] == "BTC-USD"

    def test_price_is_string(self, normalizer: KrakenNormalizer) -> None:
        result = normalizer.normalize(_ticker_msg([_item(last=65000.5)]))
        assert result[0].payload["price"] == "65000.5"
        assert isinstance(result[0].payload["price"], str)

    def test_bid_ask_are_strings(self, normalizer: KrakenNormalizer) -> None:
        result = normalizer.normalize(_ticker_msg([_item(bid=65000.0, ask=65001.0)]))
        assert result[0].payload["best_bid"] == "65000.0"
        assert result[0].payload["best_ask"] == "65001.0"

    def test_volume_and_range_present(self, normalizer: KrakenNormalizer) -> None:
        result = normalizer.normalize(_ticker_msg([_item()]))
        p = result[0].payload
        assert "volume_24h" in p
        assert "low_24h" in p
        assert "high_24h" in p

    def test_change_pct_mapped(self, normalizer: KrakenNormalizer) -> None:
        result = normalizer.normalize(_ticker_msg([_item(change_pct=1.56)]))
        assert result[0].payload["price_change_pct_24h"] == "1.56"

    def test_venue_is_kraken(self, normalizer: KrakenNormalizer) -> None:
        result = normalizer.normalize(_ticker_msg([_item()]))
        assert result[0].payload["venue"] == "kraken"


class TestTickerSnapshot:
    def test_snapshot_also_produces_envelopes(self, normalizer: KrakenNormalizer) -> None:
        result = normalizer.normalize(_ticker_msg([_item()], msg_type="snapshot"))
        assert len(result) == 1
        assert result[0].event_type == EventType.MARKET_TICK


# ---------------------------------------------------------------------------
# Guard conditions
# ---------------------------------------------------------------------------


class TestGuards:
    def test_missing_last_skips_item(self, normalizer: KrakenNormalizer) -> None:
        item = _item()
        del item["last"]
        result = normalizer.normalize(_ticker_msg([item]))
        assert result == []

    def test_missing_symbol_skips_item(self, normalizer: KrakenNormalizer) -> None:
        item = _item()
        del item["symbol"]
        result = normalizer.normalize(_ticker_msg([item]))
        assert result == []

    def test_optional_field_absent_not_in_payload(self, normalizer: KrakenNormalizer) -> None:
        item = {"symbol": "BTC/USD", "last": 65000.0}  # minimal item
        result = normalizer.normalize(_ticker_msg([item]))
        assert len(result) == 1
        assert "best_bid" not in result[0].payload
        assert "volume_24h" not in result[0].payload

    def test_ticker_type_other_than_update_snapshot_ignored(
        self, normalizer: KrakenNormalizer
    ) -> None:
        msg = {"channel": "ticker", "type": "unknown_type", "data": [_item()]}
        assert normalizer.normalize(msg) == []


# ---------------------------------------------------------------------------
# Non-ticker channels
# ---------------------------------------------------------------------------


class TestNonTickerChannels:
    def test_heartbeat_returns_empty(self, normalizer: KrakenNormalizer) -> None:
        msg = {
            "channel": "heartbeat",
            "type": "update",
            "data": [{"timestamp": "2026-06-09T12:00:00.000000Z"}],
        }
        assert normalizer.normalize(msg) == []

    def test_status_returns_empty(self, normalizer: KrakenNormalizer) -> None:
        msg = {
            "channel": "status",
            "type": "update",
            "data": [{"system": "online", "version": "2.0.0"}],
        }
        assert normalizer.normalize(msg) == []

    def test_subscribe_confirmation_returns_empty(self, normalizer: KrakenNormalizer) -> None:
        # Subscribe confirmations use "method" not "channel" — handled by the feed, not normalizer
        msg = {"method": "subscribe", "success": True, "result": {"channel": "ticker"}}
        assert normalizer.normalize(msg) == []

    def test_empty_channel_returns_empty(self, normalizer: KrakenNormalizer) -> None:
        assert normalizer.normalize({}) == []
