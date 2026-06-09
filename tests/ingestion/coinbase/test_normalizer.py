"""
Tests for CoinbaseNormalizer.

Pure unit tests — no I/O, no bus, no WebSocket.
All Coinbase wire-format edge cases live here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.schemas import EventType
from ingestion.coinbase.normalizer import CoinbaseNormalizer, _parse_ts


# ---------------------------------------------------------------------------
# Fixtures — realistic Coinbase wire messages
# ---------------------------------------------------------------------------

TICKER_TS = "2026-06-09T18:00:00.123456789Z"  # nanosecond precision

TICKER_MSG: dict = {
    "channel": "ticker",
    "client_id": "",
    "timestamp": TICKER_TS,
    "sequence_num": 1,
    "events": [
        {
            "type": "update",
            "tickers": [
                {
                    "type": "ticker",
                    "product_id": "BTC-USD",
                    "price": "65000.00",
                    "best_bid": "64999.00",
                    "best_ask": "65001.00",
                    "best_bid_quantity": "0.10",
                    "best_ask_quantity": "0.20",
                    "volume_24_h": "1234.56",
                    "low_24_h": "64000.00",
                    "high_24_h": "66000.00",
                    "price_percent_chg_24_h": "1.538",
                }
            ],
        }
    ],
}

MULTI_TICKER_MSG: dict = {
    "channel": "ticker",
    "timestamp": TICKER_TS,
    "events": [
        {
            "type": "snapshot",
            "tickers": [
                {"product_id": "BTC-USD", "price": "65000.00"},
                {"product_id": "ETH-USD", "price": "3500.00"},
            ],
        }
    ],
}

SUBSCRIPTIONS_MSG: dict = {
    "channel": "subscriptions",
    "events": [{"subscriptions": {"ticker": ["BTC-USD", "ETH-USD"]}}],
}

ERROR_MSG: dict = {
    "channel": "error",
    "message": "Subscription failed",
    "events": [],
}


@pytest.fixture
def normalizer() -> CoinbaseNormalizer:
    return CoinbaseNormalizer()


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_nanosecond_precision_truncated(self) -> None:
        # Python datetime max is microseconds — 9-digit fraction must be trimmed
        dt = _parse_ts("2026-06-09T18:00:00.123456789Z")
        assert dt.microsecond == 123456
        assert dt.tzinfo is not None

    def test_microsecond_precision_unchanged(self) -> None:
        dt = _parse_ts("2026-06-09T18:00:00.123456Z")
        assert dt.microsecond == 123456

    def test_z_suffix_replaced_with_utc_offset(self) -> None:
        dt = _parse_ts("2026-06-09T18:00:00Z")
        assert dt.utcoffset().total_seconds() == 0  # type: ignore[union-attr]

    def test_result_is_utc_aware(self) -> None:
        dt = _parse_ts("2026-06-09T18:00:00.000000Z")
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# Normalizer — ticker channel
# ---------------------------------------------------------------------------


class TestNormalizerTicker:
    def test_produces_one_market_tick_envelope(self, normalizer: CoinbaseNormalizer) -> None:
        envelopes = normalizer.normalize(TICKER_MSG)
        assert len(envelopes) == 1
        assert envelopes[0].event_type == EventType.MARKET_TICK

    def test_source_is_coinbase_ws(self, normalizer: CoinbaseNormalizer) -> None:
        env = normalizer.normalize(TICKER_MSG)[0]
        assert env.source == "coinbase_ws"

    def test_payload_instrument(self, normalizer: CoinbaseNormalizer) -> None:
        payload = normalizer.normalize(TICKER_MSG)[0].payload
        assert payload["instrument"] == "BTC-USD"

    def test_payload_venue(self, normalizer: CoinbaseNormalizer) -> None:
        payload = normalizer.normalize(TICKER_MSG)[0].payload
        assert payload["venue"] == "coinbase"

    def test_payload_price_preserved_as_string(self, normalizer: CoinbaseNormalizer) -> None:
        # Prices must stay as strings to preserve Decimal precision
        payload = normalizer.normalize(TICKER_MSG)[0].payload
        assert payload["price"] == "65000.00"
        assert isinstance(payload["price"], str)

    def test_payload_bid_ask(self, normalizer: CoinbaseNormalizer) -> None:
        payload = normalizer.normalize(TICKER_MSG)[0].payload
        assert payload["best_bid"] == "64999.00"
        assert payload["best_ask"] == "65001.00"

    def test_payload_volume_and_range(self, normalizer: CoinbaseNormalizer) -> None:
        payload = normalizer.normalize(TICKER_MSG)[0].payload
        assert payload["volume_24h"] == "1234.56"
        assert payload["low_24h"] == "64000.00"
        assert payload["high_24h"] == "66000.00"

    def test_payload_price_change_pct(self, normalizer: CoinbaseNormalizer) -> None:
        payload = normalizer.normalize(TICKER_MSG)[0].payload
        assert payload["price_change_pct_24h"] == "1.538"

    def test_event_time_parsed_from_channel_timestamp(
        self, normalizer: CoinbaseNormalizer
    ) -> None:
        env = normalizer.normalize(TICKER_MSG)[0]
        # Nanoseconds truncated to microseconds
        assert env.event_time.microsecond == 123456
        assert env.event_time.tzinfo is not None

    def test_venue_timestamp_in_payload(self, normalizer: CoinbaseNormalizer) -> None:
        payload = normalizer.normalize(TICKER_MSG)[0].payload
        assert payload["venue_timestamp"] == TICKER_TS

    def test_multiple_tickers_produce_multiple_envelopes(
        self, normalizer: CoinbaseNormalizer
    ) -> None:
        envelopes = normalizer.normalize(MULTI_TICKER_MSG)
        assert len(envelopes) == 2
        instruments = {e.payload["instrument"] for e in envelopes}
        assert instruments == {"BTC-USD", "ETH-USD"}

    def test_none_fields_excluded_from_payload(
        self, normalizer: CoinbaseNormalizer
    ) -> None:
        # Ticker with only required fields — optional fields should not appear
        msg = {
            "channel": "ticker",
            "timestamp": TICKER_TS,
            "events": [{"type": "update", "tickers": [{"product_id": "BTC-USD", "price": "65000"}]}],
        }
        payload = normalizer.normalize(msg)[0].payload
        assert "best_bid" not in payload
        assert "volume_24h" not in payload

    def test_ticker_missing_product_id_skipped(
        self, normalizer: CoinbaseNormalizer
    ) -> None:
        msg = {
            "channel": "ticker",
            "timestamp": TICKER_TS,
            "events": [{"type": "update", "tickers": [{"price": "65000"}]}],
        }
        assert normalizer.normalize(msg) == []

    def test_empty_events_list(self, normalizer: CoinbaseNormalizer) -> None:
        msg = {"channel": "ticker", "timestamp": TICKER_TS, "events": []}
        assert normalizer.normalize(msg) == []

    def test_bad_timestamp_falls_back_gracefully(
        self, normalizer: CoinbaseNormalizer
    ) -> None:
        msg = {**TICKER_MSG, "timestamp": "not-a-date"}
        envelopes = normalizer.normalize(msg)
        # Still produces envelopes — bad timestamp doesn't kill the message
        assert len(envelopes) == 1
        # event_time falls back to a fresh datetime.now(UTC)
        assert (datetime.now(UTC) - envelopes[0].event_time).total_seconds() < 5

    def test_missing_timestamp_falls_back_gracefully(
        self, normalizer: CoinbaseNormalizer
    ) -> None:
        msg = {k: v for k, v in TICKER_MSG.items() if k != "timestamp"}
        envelopes = normalizer.normalize(msg)
        assert len(envelopes) == 1


# ---------------------------------------------------------------------------
# Normalizer — other channels
# ---------------------------------------------------------------------------


class TestNormalizerOtherChannels:
    def test_subscriptions_message_returns_empty(
        self, normalizer: CoinbaseNormalizer
    ) -> None:
        assert normalizer.normalize(SUBSCRIPTIONS_MSG) == []

    def test_error_message_returns_empty(self, normalizer: CoinbaseNormalizer) -> None:
        assert normalizer.normalize(ERROR_MSG) == []

    def test_unknown_channel_returns_empty(self, normalizer: CoinbaseNormalizer) -> None:
        assert normalizer.normalize({"channel": "some_future_channel", "events": []}) == []

    def test_empty_message_returns_empty(self, normalizer: CoinbaseNormalizer) -> None:
        assert normalizer.normalize({}) == []


# ---------------------------------------------------------------------------
# Feed._dispatch path (tests the feed's parse + route without a real WS)
# ---------------------------------------------------------------------------


class TestFeedDispatch:
    """
    Test CoinbaseFeed._dispatch by calling it directly with raw JSON strings.
    No WebSocket, no bus connection — uses InMemoryEventStore via InProcessBus.
    """

    @pytest.fixture
    def bus_and_store(self):
        from core.bus import InMemoryEventStore, InProcessBus

        store = InMemoryEventStore()
        return InProcessBus(store), store

    @pytest.fixture
    def feed(self, bus_and_store):
        from ingestion.coinbase.feed import CoinbaseFeed
        from ingestion.coinbase.settings import CoinbaseFeedSettings

        bus, _ = bus_and_store
        return CoinbaseFeed(bus, CoinbaseFeedSettings(ws_url="wss://test", products=["BTC-USD"]))

    async def test_ticker_json_lands_in_store(self, feed, bus_and_store) -> None:
        import json

        _, store = bus_and_store
        await feed._dispatch(json.dumps(TICKER_MSG))
        assert len(store.events) == 1
        assert store.events[0].event_type == EventType.MARKET_TICK

    async def test_subscriptions_publishes_feed_healthy(self, feed, bus_and_store) -> None:
        import json

        _, store = bus_and_store
        await feed._dispatch(json.dumps(SUBSCRIPTIONS_MSG))
        types = [e.event_type for e in store.events]
        assert EventType.SYSTEM_FEED_HEALTHY in types

    async def test_invalid_json_does_not_raise(self, feed) -> None:
        await feed._dispatch("this is not json {{{{")

    async def test_empty_json_object_does_not_raise(self, feed) -> None:
        await feed._dispatch("{}")
