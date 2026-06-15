"""
Senate-LDA lobbying filings and USASpending contract awards → signal.created.

Two normalizers, both tied to a ticker the caller already resolved (the API was
queried by that ticker's company name). Both carry factor="government_exposure"
so they don't double-count with congressional signals on the same name (ADR-010).

Two-clock rule (PLANNING §4.6): event_time is the public-disclosure date —
lobbying `dt_posted`, contract `Base Obligation Date` — not any earlier internal date.

Direction:
  - contract award → "buy": a new federal award is incoming revenue (directional;
    a thesis seed on its own).
  - lobbying → "neutral": engagement context, not a directional trade signal
    (contributes to a thesis but does not seed one — see thesis generator).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from core.schemas.common import Provenance
from core.schemas.events import EventEnvelope, EventType
from core.schemas.signal import Signal, SignalType

_LDA_SOURCE = "senate_lda"
_USASPENDING_SOURCE = "usaspending"


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").lstrip("$"))
    except InvalidOperation:
        return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _envelope(signal: Signal, source: str, event_time: datetime, now: datetime) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.SIGNAL_CREATED,
        source=source,
        event_time=event_time,
        ingest_time=now,
        payload=signal.model_dump(mode="json"),
    )


def _issues(filing: dict[str, Any]) -> str:
    activities = filing.get("lobbying_activities") or []
    names = [
        a["general_issue_code_display"]
        for a in activities
        if isinstance(a, dict) and a.get("general_issue_code_display")
    ]
    return ", ".join(dict.fromkeys(names))[:120]  # de-dup, preserve order, cap


def normalize_lobbying(
    filing: dict[str, Any], ticker: str, min_usd: Decimal
) -> EventEnvelope | None:
    amount = _dec(filing.get("income")) or _dec(filing.get("expenses"))
    if amount is None or amount < min_usd:
        return None
    posted = _parse_dt(filing.get("dt_posted"))
    if posted is None:
        return None

    uid = str(filing.get("filing_uuid") or "")
    if not uid:
        return None
    client = (filing.get("client") or {}).get("name") or ticker
    registrant = (filing.get("registrant") or {}).get("name") or "a lobbying firm"
    issues = _issues(filing)
    issue_ctx = f" on {issues}" if issues else ""

    summary = (
        f"Lobbying disclosure: {registrant} reported ${amount:,.0f} lobbying for "
        f"{client}{issue_ctx}; disclosed {posted.date().isoformat()}."
    )
    now = datetime.now(UTC)
    signal = Signal(
        type=SignalType.LOBBYING,
        instruments=[ticker],
        provenance=Provenance(
            source=_LDA_SOURCE,
            source_id=uid,
            event_time=posted,
            ingest_time=now,
            url=filing.get("filing_document_url"),
        ),
        relevance_score=min(1.0, float(amount) / float(min_usd * 5)),
        payload={
            "summary": summary,
            "factor": "government_exposure",
            "direction": "neutral",  # contextual — not a thesis seed
            "registrant": registrant,
            "client": client,
            "issues": issues,
            "amount_usd": str(amount),
            "filing_year": filing.get("filing_year"),
        },
    )
    return _envelope(signal, _LDA_SOURCE, posted, now)


def normalize_contract(
    award: dict[str, Any], ticker: str, min_usd: Decimal
) -> EventEnvelope | None:
    amount = _dec(award.get("Award Amount"))
    if amount is None or amount < min_usd:
        return None
    action = _parse_dt(award.get("Base Obligation Date"))
    if action is None:
        return None

    internal_id = str(award.get("generated_internal_id") or "")
    aid = internal_id or str(award.get("Award ID") or "")
    if not aid:
        return None
    # Public award page — only generated_internal_id routes there; Award ID won't.
    url = f"https://www.usaspending.gov/award/{internal_id}/" if internal_id else None
    recipient = award.get("Recipient Name") or ticker
    agency = award.get("Awarding Agency") or "a federal agency"
    desc = (award.get("Description") or "").strip()
    desc_ctx = f" — {desc[:100]}" if desc else ""

    summary = (
        f"Government contract: {recipient} awarded ${amount:,.0f} by {agency}{desc_ctx}; "
        f"action {action.date().isoformat()}."
    )
    now = datetime.now(UTC)
    signal = Signal(
        type=SignalType.GOV_CONTRACT,
        instruments=[ticker],
        provenance=Provenance(
            source=_USASPENDING_SOURCE,
            source_id=aid,
            event_time=action,
            ingest_time=now,
            url=url,
        ),
        relevance_score=min(1.0, float(amount) / float(min_usd * 10)),
        payload={
            "summary": summary,
            "factor": "government_exposure",
            "direction": "buy",  # new federal revenue → bullish
            "recipient": recipient,
            "agency": agency,
            "amount_usd": str(amount),
            "award_id": aid,
        },
    )
    return _envelope(signal, _USASPENDING_SOURCE, action, now)
