"""Tests for on-demand OHLC history (chart UI). Network replaced by MockTransport."""

from __future__ import annotations

import httpx
import pytest

from ingestion.equity.settings import EquityFeedSettings
from ingestion.history import (
    HistoryUnavailable,
    fetch_ohlc,
    is_crypto,
    parse_alpaca_bars,
    parse_kraken_ohlc,
)

_KRAKEN = {
    "error": [],
    "result": {
        # Kraken's internal pair name, not what we asked for — parser must find it.
        "XXBTZUSD": [
            [1718668800, "65000.0", "66000.0", "64000.0", "65500.0", "65200.0", "1234.5", 100],
            [1718755200, "65500.0", "67000.0", "65100.0", "66800.0", "66200.0", "2000.0", 120],
        ],
        "last": 1718755200,
    },
}

_ALPACA = {
    "bars": [
        {"t": "2026-06-17T13:30:00Z", "o": 100.0, "h": 105.0, "l": 99.0, "c": 104.0, "v": 1000},
        {"t": "2026-06-17T14:30:00Z", "o": 104.0, "h": 106.0, "l": 103.0, "c": 103.5, "v": 1500},
    ],
    "symbol": "AAPL",
}


def _transport(body: dict, status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(lambda req: httpx.Response(status, json=body))


class TestMarketInference:
    def test_dash_is_crypto(self) -> None:
        assert is_crypto("BTC-USD") is True

    def test_plain_ticker_is_equity(self) -> None:
        assert is_crypto("AAPL") is False


class TestParsers:
    def test_kraken_picks_pair_key_and_maps_columns(self) -> None:
        bars = parse_kraken_ohlc(_KRAKEN)
        assert len(bars) == 2
        b = bars[0]
        assert (b.o, b.h, b.l, b.c, b.v) == (65000.0, 66000.0, 64000.0, 65500.0, 1234.5)
        assert b.t == 1718668800  # epoch seconds, passed through

    def test_kraken_empty_result(self) -> None:
        assert parse_kraken_ohlc({"result": {"last": 0}}) == []

    def test_alpaca_maps_and_converts_timestamp(self) -> None:
        from datetime import datetime

        bars = parse_alpaca_bars(_ALPACA)
        assert len(bars) == 2
        assert bars[0].t == int(datetime.fromisoformat("2026-06-17T13:30:00Z").timestamp())
        assert bars[1].t > bars[0].t  # 1h later
        assert bars[1].c == 103.5

    def test_alpaca_null_bars(self) -> None:
        assert parse_alpaca_bars({"bars": None}) == []


class TestFetch:
    async def test_crypto_fetches_and_trims_to_window(self) -> None:
        # The 1Y spec keeps up to 366 bars, so both returned bars survive…
        bars = await fetch_ohlc("BTC-USD", range_key="1Y", transport=_transport(_KRAKEN))
        assert [b.t for b in bars] == [1718668800, 1718755200]

    async def test_unknown_range_falls_back_to_default(self) -> None:
        bars = await fetch_ohlc("BTC-USD", range_key="bogus", transport=_transport(_KRAKEN))
        assert len(bars) == 2

    async def test_kraken_error_raises(self) -> None:
        body = {"error": ["EQuery:Unknown asset pair"], "result": {}}
        with pytest.raises(HistoryUnavailable):
            await fetch_ohlc("ZZZ-USD", range_key="1M", transport=_transport(body))

    async def test_equity_without_key_raises(self) -> None:
        with pytest.raises(HistoryUnavailable, match="EQUITY_FEED_API_KEY"):
            await fetch_ohlc(
                "AAPL",
                range_key="1M",
                settings=EquityFeedSettings(api_key=""),
                transport=_transport(_ALPACA),
            )

    async def test_equity_with_key_fetches(self) -> None:
        settings = EquityFeedSettings(api_key="k", api_secret="s")
        bars = await fetch_ohlc(
            "AAPL", range_key="1D", settings=settings, transport=_transport(_ALPACA)
        )
        assert [b.c for b in bars] == [104.0, 103.5]
