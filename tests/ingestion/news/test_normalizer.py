"""Tests for NewsNormalizer.normalize()."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import pytest

from core.schemas.events import EventType
from core.schemas.signal import SignalType
from ingestion.news.normalizer import NewsNormalizer


def _entry(**kwargs: Any) -> dict[str, Any]:
    """Minimal valid entry with optional overrides."""
    base: dict[str, Any] = {
        "title": "Bitcoin Reaches New High",
        "link": "https://coindesk.com/story/123",
        "summary": "BTC surged today.",
        "published_parsed": time.strptime("2026-06-09 12:00:00", "%Y-%m-%d %H:%M:%S"),
    }
    base.update(kwargs)
    return base


@pytest.fixture
def normalizer() -> NewsNormalizer:
    return NewsNormalizer()


# ---------------------------------------------------------------------------
# Guard conditions
# ---------------------------------------------------------------------------


class TestGuards:
    def test_returns_none_if_no_title(self, normalizer: NewsNormalizer) -> None:
        assert normalizer.normalize(_entry(title="")) is None

    def test_returns_none_if_title_is_whitespace(self, normalizer: NewsNormalizer) -> None:
        assert normalizer.normalize(_entry(title="   ")) is None

    def test_returns_none_if_no_link(self, normalizer: NewsNormalizer) -> None:
        assert normalizer.normalize(_entry(link="")) is None


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class TestEnvelopeShape:
    def test_event_type_is_signal_created(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(_entry())
        assert env is not None
        assert env.event_type == EventType.SIGNAL_CREATED

    def test_source_is_rss_news_feed(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(_entry())
        assert env is not None
        assert env.source == "rss_news_feed"

    def test_signal_type_is_news(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(_entry())
        assert env is not None
        assert env.payload["type"] == SignalType.NEWS


# ---------------------------------------------------------------------------
# Instrument extraction
# ---------------------------------------------------------------------------


class TestInstrumentExtraction:
    def test_extracts_bitcoin_from_title(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(_entry(title="Bitcoin Hits $70k", summary=""))
        assert env is not None
        assert "BTC-USD" in env.payload["instruments"]

    def test_extracts_btc_abbreviation(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(_entry(title="BTC price update", summary=""))
        assert env is not None
        assert "BTC-USD" in env.payload["instruments"]

    def test_extracts_ethereum(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(_entry(title="Ethereum upgrade complete", summary=""))
        assert env is not None
        assert "ETH-USD" in env.payload["instruments"]

    def test_extracts_multiple_instruments(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(
            _entry(title="Bitcoin and Ethereum both rally", summary="")
        )
        assert env is not None
        instruments = env.payload["instruments"]
        assert "BTC-USD" in instruments
        assert "ETH-USD" in instruments

    def test_instruments_empty_when_none_mentioned(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(_entry(title="Fed raises rates", summary=""))
        assert env is not None
        assert env.payload["instruments"] == []

    def test_instruments_sorted(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(
            _entry(title="Solana ethereum bitcoin", summary="")
        )
        assert env is not None
        instruments = env.payload["instruments"]
        assert instruments == sorted(instruments)

    def test_extracts_instrument_from_summary_too(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(
            _entry(title="Market update", summary="Ethereum shows strength")
        )
        assert env is not None
        assert "ETH-USD" in env.payload["instruments"]


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------


class TestDateParsing:
    def test_uses_published_parsed(self, normalizer: NewsNormalizer) -> None:
        ts = time.strptime("2026-01-15 09:30:00", "%Y-%m-%d %H:%M:%S")
        env = normalizer.normalize(_entry(published_parsed=ts))
        assert env is not None
        assert env.event_time == datetime(2026, 1, 15, 9, 30, 0, tzinfo=UTC)

    def test_falls_back_to_now_if_no_date(self, normalizer: NewsNormalizer) -> None:
        before = datetime.now(UTC)
        env = normalizer.normalize(_entry(published_parsed=None, updated_parsed=None))
        after = datetime.now(UTC)
        assert env is not None
        assert before <= env.event_time <= after


# ---------------------------------------------------------------------------
# Payload content
# ---------------------------------------------------------------------------


class TestPayload:
    def test_payload_includes_title(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(_entry(title="Big BTC news"))
        assert env is not None
        assert env.payload["payload"]["title"] == "Big BTC news"

    def test_payload_strips_html_from_summary(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(
            _entry(summary="<p>Bitcoin <strong>surges</strong> 10%.</p>")
        )
        assert env is not None
        assert "<" not in env.payload["payload"]["summary"]
        assert "Bitcoin" in env.payload["payload"]["summary"]

    def test_payload_truncates_long_summary(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(_entry(summary="x" * 1000))
        assert env is not None
        assert len(env.payload["payload"]["summary"]) <= 500

    def test_payload_includes_source_domain(self, normalizer: NewsNormalizer) -> None:
        env = normalizer.normalize(
            _entry(link="https://www.coindesk.com/story/abc")
        )
        assert env is not None
        assert env.payload["payload"]["source_domain"] == "coindesk.com"

    def test_provenance_source_id_is_link(self, normalizer: NewsNormalizer) -> None:
        link = "https://coindesk.com/story/123"
        env = normalizer.normalize(_entry(link=link))
        assert env is not None
        assert env.payload["provenance"]["source_id"] == link
