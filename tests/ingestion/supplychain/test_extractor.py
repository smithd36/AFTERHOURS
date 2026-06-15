"""Tests for the 10-K customer-concentration extractor and signal builder."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from ingestion.supplychain.extractor import build_signal, extract_dependency, strip_html

_MIN = Decimal("10")
_FILED = datetime(2026, 3, 1, tzinfo=UTC)


def test_extracts_highest_material_concentration() -> None:
    text = (
        "We have many customers. Customer A accounted for 23% of our net revenue in fiscal 2025. "
        "Customer B represented 11% of sales. Unrelated sentence about weather."
    )
    dep = extract_dependency(text, _MIN)
    assert dep is not None
    pct, sentence = dep
    assert pct == Decimal("23")
    assert "Customer A" in sentence


def test_sub_threshold_returns_none() -> None:
    text = "Customer A accounted for 5% of our revenue."
    assert extract_dependency(text, _MIN) is None


def test_percentage_without_customer_keyword_ignored() -> None:
    text = "Our gross margin improved to 45% of revenue this year."
    assert extract_dependency(text, _MIN) is None


def test_customer_without_revenue_keyword_ignored() -> None:
    text = "Customer satisfaction rose 30% year over year."
    assert extract_dependency(text, _MIN) is None


def test_strip_html_removes_tags_and_entities() -> None:
    assert strip_html("<p>Customer&nbsp;A &amp; B</p>") == "Customer A & B"


def test_build_signal_is_neutral_supply_chain() -> None:
    text = "Customer A accounted for 23% of our net revenue."
    env = build_signal(text, "AAPL", _FILED, "0000-24-1", "http://x/10k.htm", _MIN)
    assert env is not None
    assert env.payload["type"] == "supply_chain"
    assert env.payload["instruments"] == ["AAPL"]
    assert env.payload["payload"]["direction"] == "neutral"
    assert env.payload["payload"]["factor"] == "supply_chain"
    assert env.payload["payload"]["revenue_pct"] == "23"
    assert env.event_time == _FILED  # two-clock: 10-K filing date


def test_build_signal_none_when_no_dependency() -> None:
    assert build_signal("nothing material here.", "AAPL", _FILED, "a", "u", _MIN) is None
