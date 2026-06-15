"""Tests for the Quiver congress-trade normalizer (materiality, direction, two-clock)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ingestion.congress.normalizer import CongressNormalizer
from ingestion.congress.settings import CongressFeedSettings


def _settings(min_usd: str = "50000") -> CongressFeedSettings:
    return CongressFeedSettings(min_amount_usd=Decimal(min_usd))


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "Representative": "Nancy Pelosi",
        "Ticker": "NVDA",
        "Transaction": "Purchase",
        "Range": "$1,000,001 - $5,000,000",
        "House": "Representatives",
        "TransactionDate": "2026-05-01",
        "ReportDate": "2026-06-10",
    }
    row.update(over)
    return row


def test_material_purchase_emits_buy_signal() -> None:
    env = CongressNormalizer(_settings()).normalize(_row())
    assert env is not None
    assert env.payload["type"] == "congressional_tx"
    assert env.payload["instruments"] == ["NVDA"]
    assert env.payload["payload"]["direction"] == "buy"
    assert env.payload["payload"]["factor"] == "government_exposure"
    assert env.payload["payload"]["actor"] == "Nancy Pelosi"


def test_event_time_is_report_date_not_transaction_date() -> None:
    # Two-clock rule: event_time = disclosure (ReportDate), never the txn date.
    env = CongressNormalizer(_settings()).normalize(_row())
    assert env is not None
    assert env.event_time == datetime(2026, 6, 10, tzinfo=UTC)
    assert env.payload["payload"]["transaction_date"] == "2026-05-01"


def test_sub_threshold_range_dropped() -> None:
    env = CongressNormalizer(_settings()).normalize(_row(Range="$1,001 - $15,000"))
    assert env is None


def test_sale_emits_sell() -> None:
    env = CongressNormalizer(_settings()).normalize(_row(Transaction="Sale (Partial)"))
    assert env is not None
    assert env.payload["payload"]["direction"] == "sell"


def test_missing_ticker_returns_none() -> None:
    assert CongressNormalizer(_settings()).normalize(_row(Ticker="")) is None


def test_non_directional_transaction_returns_none() -> None:
    assert CongressNormalizer(_settings()).normalize(_row(Transaction="Exchange")) is None


def test_range_lower_bound_used_for_materiality() -> None:
    # Lower bound 50,001 ≥ 50,000 floor → material.
    env = CongressNormalizer(_settings()).normalize(_row(Range="$50,001 - $100,000"))
    assert env is not None
    assert env.payload["payload"]["amount_usd_low"] == "50001"
