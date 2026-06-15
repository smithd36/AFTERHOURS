"""
SEC Form 4 (insider transaction) ownership XML → EventEnvelope(signal.created).

Materiality filter: only open-market purchases (code P) and sales (code S) above
a USD floor become signals. Grants, option exercises, gifts, and tax-withholding
(codes A/M/G/F, …) are deliberately dropped — they are not discretionary informed
trades and would be noise to the reasoning layer.

Two-clock rule (PLANNING §4.6): event_time is the filing's public-availability
timestamp (when we could first act), NOT the transaction date — using the
transaction date would be look-ahead bias. transaction_date is kept in the
payload as context only.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from core.schemas.common import Provenance
from core.schemas.events import EventEnvelope, EventType
from core.schemas.signal import Signal, SignalType

from .settings import InsiderFeedSettings

_SOURCE = "sec_edgar_form4"
_OPEN_MARKET = {"P", "S"}  # P = open-market purchase, S = open-market sale


def _t(elem: ET.Element, path: str) -> str | None:
    text = elem.findtext(path)
    stripped = text.strip() if text else ""
    return stripped or None


def _dec(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


class Form4Normalizer:
    """Converts one Form 4 ownershipDocument XML string into an EventEnvelope or None."""

    def __init__(self, settings: InsiderFeedSettings) -> None:
        self._min_usd = settings.min_transaction_usd

    def normalize(
        self, doc_xml: str, accession: str, url: str, accepted: datetime
    ) -> EventEnvelope | None:
        # Form 4 ownership documents are not namespaced — bare element paths.
        try:
            root = ET.fromstring(doc_xml)
        except ET.ParseError:
            return None

        symbol = _t(root, "./issuer/issuerTradingSymbol")
        if not symbol:
            return None
        symbol = symbol.upper()

        buy_usd = Decimal(0)
        sell_usd = Decimal(0)
        for tx in root.findall("./nonDerivativeTable/nonDerivativeTransaction"):
            code = _t(tx, "./transactionCoding/transactionCode")
            if code not in _OPEN_MARKET:
                continue
            shares = _dec(_t(tx, "./transactionAmounts/transactionShares/value"))
            price = _dec(_t(tx, "./transactionAmounts/transactionPricePerShare/value"))
            if shares is None or price is None or price <= 0:
                continue
            value = shares * price
            if code == "P":
                buy_usd += value
            else:
                sell_usd += value

        if buy_usd == 0 and sell_usd == 0:
            return None
        direction, amount = ("buy", buy_usd) if buy_usd >= sell_usd else ("sell", sell_usd)
        if amount < self._min_usd:
            return None

        owner = _t(root, "./reportingOwner/reportingOwnerId/rptOwnerName") or "unknown insider"
        title = _t(root, "./reportingOwner/reportingOwnerRelationship/officerTitle")
        period = _t(root, "./periodOfReport")

        who = f"{owner} ({title})" if title else owner
        verb = "purchased" if direction == "buy" else "sold"
        ctx = f"transaction {period}, " if period else ""
        # The summary is the only field the thesis prompt renders — pack the
        # material facts into it (see reasoning/thesis/prompt.py).
        summary = (
            f"Form 4 insider {direction}: {who} {verb} ${amount:,.0f} of {symbol} "
            f"in open-market transactions ({ctx}disclosed {accepted.date().isoformat()})."
        )

        now = datetime.now(UTC)
        signal = Signal(
            type=SignalType.INSIDER_TX,
            instruments=[symbol],
            provenance=Provenance(
                source=_SOURCE,
                source_id=accession,
                event_time=accepted,
                ingest_time=now,
                url=url,
            ),
            relevance_score=min(1.0, float(amount) / float(self._min_usd * 10)),
            payload={
                "summary": summary,
                "factor": "insider_activity",  # correlation family (ADR-010 §correlation)
                "direction": direction,
                "actor": owner,
                "actor_title": title,
                "amount_usd": str(amount.quantize(Decimal("0.01"))),
                "transaction_date": period,  # context only — never event_time
                "accession": accession,
                "form": "4",
            },
        )
        return EventEnvelope(
            event_type=EventType.SIGNAL_CREATED,
            source=_SOURCE,
            event_time=accepted,
            ingest_time=now,
            payload=signal.model_dump(mode="json"),
        )
