"""Tests for the lobbying + contract normalizers (materiality, direction, two-clock)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ingestion.govexposure.normalizer import normalize_contract, normalize_lobbying

_MIN_LOBBY = Decimal("50000")
_MIN_CONTRACT = Decimal("1000000")


def _filing(**over: Any) -> dict[str, Any]:
    filing: dict[str, Any] = {
        "filing_uuid": "lda-1",
        "income": "120000.00",
        "dt_posted": "2026-06-10T12:00:00Z",
        "filing_year": 2026,
        "client": {"name": "Apple Inc."},
        "registrant": {"name": "Big Lobby LLC"},
        "lobbying_activities": [{"general_issue_code_display": "Taxation"}],
    }
    filing.update(over)
    return filing


def _award(**over: Any) -> dict[str, Any]:
    award: dict[str, Any] = {
        "generated_internal_id": "ct-1",
        "Recipient Name": "Apple Inc.",
        "Award Amount": 5_000_000,
        "Base Obligation Date": "2026-06-09",
        "Awarding Agency": "Department of Defense",
        "Description": "Logistics support",
    }
    award.update(over)
    return award


def test_material_lobbying_is_neutral_signal() -> None:
    env = normalize_lobbying(_filing(), "AAPL", _MIN_LOBBY)
    assert env is not None
    assert env.payload["type"] == "lobbying"
    assert env.payload["instruments"] == ["AAPL"]
    assert env.payload["payload"]["direction"] == "neutral"
    assert env.payload["payload"]["factor"] == "government_exposure"
    # Two-clock: event_time = disclosure (dt_posted).
    assert env.event_time == datetime(2026, 6, 10, 12, tzinfo=UTC)


def test_sub_threshold_lobbying_dropped() -> None:
    assert normalize_lobbying(_filing(income="1000.00", expenses=None), "AAPL", _MIN_LOBBY) is None


def test_lobbying_missing_dt_posted_dropped() -> None:
    assert normalize_lobbying(_filing(dt_posted=None), "AAPL", _MIN_LOBBY) is None


def test_material_contract_is_buy_signal() -> None:
    env = normalize_contract(_award(), "AAPL", _MIN_CONTRACT)
    assert env is not None
    assert env.payload["type"] == "gov_contract"
    assert env.payload["instruments"] == ["AAPL"]
    assert env.payload["payload"]["direction"] == "buy"
    assert env.payload["payload"]["factor"] == "government_exposure"
    # Two-clock: event_time = award Base Obligation Date.
    assert env.event_time == datetime(2026, 6, 9, tzinfo=UTC)
    # Clickable link to the public award page, keyed by generated_internal_id.
    assert env.payload["provenance"]["url"] == "https://www.usaspending.gov/award/ct-1/"


def test_sub_threshold_contract_dropped() -> None:
    assert normalize_contract(_award(**{"Award Amount": 5000}), "AAPL", _MIN_CONTRACT) is None
