"""Tests for the Alpaca snapshot → market.tick payload mapping."""

from __future__ import annotations

from typing import Any

from ingestion.equity.feed import alpaca_snapshot_to_payload


def _snapshot(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "latestTrade": {"p": 210.5},
        "latestQuote": {"bp": 210.4, "ap": 210.6},
        "dailyBar": {"o": 208.0, "h": 211.2, "l": 207.8, "c": 210.5, "v": 1_500_000},
        "prevDailyBar": {"o": 205.0, "h": 209.0, "l": 204.5, "c": 200.0, "v": 1_200_000},
    }
    base.update(overrides)
    return base


class TestAlpacaSnapshotToPayload:
    def test_full_snapshot(self) -> None:
        payload = alpaca_snapshot_to_payload(_snapshot())
        assert payload == {
            "price": "210.5",
            "best_bid": "210.4",
            "best_ask": "210.6",
            "high_24h": "211.2",
            "low_24h": "207.8",
            "volume_24h": "1500000",
            "price_change_pct_24h": "5.25",
        }

    def test_no_trade_returns_none(self) -> None:
        assert alpaca_snapshot_to_payload(_snapshot(latestTrade=None)) is None
        assert alpaca_snapshot_to_payload({}) is None

    def test_zero_bid_ask_omitted(self) -> None:
        # IEX reports 0 for an empty side of the book (e.g. outside market hours).
        payload = alpaca_snapshot_to_payload(_snapshot(latestQuote={"bp": 0, "ap": 0}))
        assert payload is not None
        assert "best_bid" not in payload
        assert "best_ask" not in payload

    def test_missing_quote_and_bars(self) -> None:
        payload = alpaca_snapshot_to_payload(
            _snapshot(latestQuote=None, dailyBar=None, prevDailyBar=None)
        )
        assert payload == {"price": "210.5"}

    def test_negative_change(self) -> None:
        payload = alpaca_snapshot_to_payload(
            _snapshot(latestTrade={"p": 190.0}, prevDailyBar={"c": 200.0})
        )
        assert payload is not None
        assert payload["price_change_pct_24h"] == "-5.00"
