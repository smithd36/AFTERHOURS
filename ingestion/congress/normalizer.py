"""
Quiver congressional-trading row → EventEnvelope(signal.created).

Materiality filter: only purchases/sales whose disclosed dollar-range LOWER
bound clears a USD floor become signals (filings report buckets, not exact
amounts). Non-trade rows (exchanges, missing ticker) are dropped.

Two-clock rule (PLANNING §4.6): event_time is the DISCLOSURE date (ReportDate —
when the trade became public), NOT the transaction date. Congressional filings
lag the trade by up to ~45 days; acting on the transaction date would be both
look-ahead bias and trading on not-yet-public information. transaction_date is
kept in the payload as context only.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from core.schemas.common import Provenance
from core.schemas.events import EventEnvelope, EventType
from core.schemas.signal import Signal, SignalType

from .settings import CongressFeedSettings

_SOURCE = "quiver_congress"
_NUM_RE = re.compile(r"[\d,]+")


def _get(row: dict[str, Any], *keys: str) -> str | None:
    """First present, non-empty value among `keys`, as a stripped string."""
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            text = str(value).strip()
            if text:
                return text
    return None


def _dec(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.replace(",", "").lstrip("$"))
    except InvalidOperation:
        return None


def _range_low(range_str: str | None) -> Decimal | None:
    """Lower bound of a disclosed range like '$1,001 - $15,000' → 1001."""
    if not range_str:
        return None
    match = _NUM_RE.search(range_str)
    if not match:
        return None
    try:
        return Decimal(match.group().replace(",", ""))
    except InvalidOperation:
        return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def dedup_key(row: dict[str, Any]) -> str:
    """Stable key for a trade — Quiver has no per-row id, so compose one."""
    fields = ("Representative", "Ticker", "TransactionDate", "Transaction", "Range")
    return "|".join(str(row.get(f, "")) for f in fields)


class CongressNormalizer:
    """Converts one Quiver congress-trade dict into an EventEnvelope or None."""

    def __init__(self, settings: CongressFeedSettings) -> None:
        self._min = settings.min_amount_usd

    def normalize(self, row: dict[str, Any]) -> EventEnvelope | None:
        ticker = _get(row, "Ticker", "ticker")
        if not ticker:
            return None
        ticker = ticker.upper()
        if ticker in ("N/A", "-", "--"):
            return None

        transaction = (_get(row, "Transaction", "transaction") or "").lower()
        if "purchase" in transaction or "buy" in transaction:
            direction = "buy"
        elif "sale" in transaction or "sell" in transaction:
            direction = "sell"
        else:
            return None  # exchanges / unknown → not a directional signal

        range_str = _get(row, "Range", "range")
        amount = _range_low(range_str) or _dec(_get(row, "Amount", "amount"))
        if amount is None or amount < self._min:
            return None

        rep = _get(row, "Representative", "representative", "Name") or "unknown member"
        chamber = _get(row, "House", "house", "Chamber") or ""
        report_date = _get(row, "ReportDate", "report_date", "Disclosed")
        txn_date = _get(row, "TransactionDate", "transaction_date")

        accepted = _parse_date(report_date) or datetime.now(UTC)

        verb = "bought" if direction == "buy" else "sold"
        chamber_ctx = f", {chamber}" if chamber else ""
        amount_ctx = range_str or f"${amount:,.0f}+"
        txn_ctx = f"; transaction {txn_date}" if txn_date else ""
        report_ctx = f", disclosed {report_date}" if report_date else ""
        # The summary is the only field the thesis prompt renders — pack it.
        summary = (
            f"Congressional {direction}: {rep}{chamber_ctx} {verb} {ticker} "
            f"({amount_ctx}){txn_ctx}{report_ctx}."
        )

        now = datetime.now(UTC)
        signal = Signal(
            type=SignalType.CONGRESSIONAL_TX,
            instruments=[ticker],
            provenance=Provenance(
                source=_SOURCE,
                source_id=dedup_key(row),
                event_time=accepted,
                ingest_time=now,
            ),
            relevance_score=min(1.0, float(amount) / float(self._min * 20)),
            payload={
                "summary": summary,
                # Shares the "government_exposure" correlation family with lobbying
                # and gov-contract signals so they don't double-count (ADR-010).
                "factor": "government_exposure",
                "direction": direction,
                "actor": rep,
                "chamber": chamber,
                "amount_usd_range": range_str,
                "amount_usd_low": str(amount),
                "transaction_date": txn_date,  # context only — never event_time
                "report_date": report_date,
            },
        )
        return EventEnvelope(
            event_type=EventType.SIGNAL_CREATED,
            source=_SOURCE,
            event_time=accepted,
            ingest_time=now,
            payload=signal.model_dump(mode="json"),
        )
