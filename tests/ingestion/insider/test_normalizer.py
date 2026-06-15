"""Tests for the Form 4 → signal normalizer (materiality, direction, two-clock)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from ingestion.insider.normalizer import Form4Normalizer
from ingestion.insider.settings import InsiderFeedSettings

_ACCEPTED = datetime(2026, 6, 11, 22, 30, tzinfo=UTC)


def _settings(min_usd: str = "100000") -> InsiderFeedSettings:
    return InsiderFeedSettings(min_transaction_usd=Decimal(min_usd))


def _doc(code: str = "P", ad: str = "A", shares: str = "10000", price: str = "195.50") -> str:
    return f"""<ownershipDocument>
  <periodOfReport>2026-06-09</periodOfReport>
  <issuer><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
  <reportingOwner><reportingOwnerId><rptOwnerName>COOK TIMOTHY D</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><officerTitle>CEO</officerTitle></reportingOwnerRelationship></reportingOwner>
  <nonDerivativeTable><nonDerivativeTransaction>
    <transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
    <transactionAmounts>
      <transactionShares><value>{shares}</value></transactionShares>
      <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
      <transactionAcquiredDisposedCode><value>{ad}</value></transactionAcquiredDisposedCode>
    </transactionAmounts>
  </nonDerivativeTransaction></nonDerivativeTable>
</ownershipDocument>"""


def test_material_purchase_emits_buy_signal() -> None:
    env = Form4Normalizer(_settings()).normalize(_doc(), "acc-1", "http://x/1.txt", _ACCEPTED)
    assert env is not None
    assert env.payload["type"] == "insider_tx"
    assert env.payload["instruments"] == ["AAPL"]
    assert env.payload["payload"]["direction"] == "buy"
    assert env.payload["payload"]["factor"] == "insider_activity"
    assert env.payload["payload"]["amount_usd"] == "1955000.00"


def test_event_time_is_disclosure_not_transaction_date() -> None:
    # Two-clock rule: event_time = availability (filing accepted), never the txn date.
    env = Form4Normalizer(_settings()).normalize(_doc(), "acc-1", "http://x/1.txt", _ACCEPTED)
    assert env is not None
    assert env.event_time == _ACCEPTED
    assert env.payload["payload"]["transaction_date"] == "2026-06-09"


def test_sub_threshold_dropped() -> None:
    # 10 shares * 195.50 = 1,955 < 100,000 floor.
    env = Form4Normalizer(_settings()).normalize(_doc(shares="10"), "a", "u", _ACCEPTED)
    assert env is None


def test_sale_emits_sell() -> None:
    env = Form4Normalizer(_settings()).normalize(_doc(code="S", ad="D"), "a", "u", _ACCEPTED)
    assert env is not None
    assert env.payload["payload"]["direction"] == "sell"


def test_option_exercise_ignored() -> None:
    # Code M (option exercise) is not an open-market trade → not material.
    env = Form4Normalizer(_settings()).normalize(_doc(code="M"), "a", "u", _ACCEPTED)
    assert env is None


def test_missing_symbol_returns_none() -> None:
    doc = "<ownershipDocument><issuer></issuer></ownershipDocument>"
    assert Form4Normalizer(_settings()).normalize(doc, "a", "u", _ACCEPTED) is None


def test_malformed_xml_returns_none() -> None:
    assert Form4Normalizer(_settings()).normalize("<not xml", "a", "u", _ACCEPTED) is None
