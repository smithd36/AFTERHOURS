"""
10-K text → supply-chain dependency signal (pure, no I/O).

Extracts customer-concentration disclosures: a sentence mentioning a customer, a
revenue keyword, and a percentage at or above the materiality threshold. Coarse
regex, not NLP (ADR-010 — public-filing proxy, deliberately simple). The matched
sentence is carried verbatim in the summary, since that is the only field the
thesis prompt renders.

direction is always "neutral": a dependency is risk context (bad if the customer
falters, good if it thrives), not a directional trade — so it enriches a thesis
but does not seed one.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from core.schemas.common import Provenance
from core.schemas.events import EventEnvelope, EventType
from core.schemas.signal import Signal, SignalType

_SOURCE = "sec_10k"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.])\s+")
_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_REV_KEYWORDS = ("revenue", "net sales", "sales", "net revenue")
_MAX_TEXT = 3_000_000  # cap scan cost on multi-MB filings


def strip_html(raw: str) -> str:
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw))).strip()


def _clean(sentence: str) -> str:
    return _WS_RE.sub(" ", sentence).strip()[:300]


def extract_dependency(text: str, min_pct: Decimal) -> tuple[Decimal, str] | None:
    """Highest-percentage customer-concentration sentence at/above min_pct, or None."""
    best: tuple[Decimal, str] | None = None
    for sentence in _SENTENCE_RE.split(text[:_MAX_TEXT]):
        low = sentence.lower()
        if "customer" not in low or not any(k in low for k in _REV_KEYWORDS):
            continue
        pcts: list[Decimal] = []
        for raw in _PCT_RE.findall(sentence):
            try:
                pct = Decimal(raw)
            except InvalidOperation:
                continue
            if pct <= 100:
                pcts.append(pct)
        if not pcts:
            continue
        top = max(pcts)
        if top < min_pct:
            continue
        if best is None or top > best[0]:
            best = (top, _clean(sentence))
    return best


def build_signal(
    text: str,
    ticker: str,
    filed: datetime,
    accession: str,
    url: str,
    min_pct: Decimal,
) -> EventEnvelope | None:
    dependency = extract_dependency(text, min_pct)
    if dependency is None:
        return None
    pct, excerpt = dependency

    summary = (
        f"Supply-chain dependency for {ticker} (10-K filed {filed.date().isoformat()}): {excerpt}"
    )
    now = datetime.now(UTC)
    signal = Signal(
        type=SignalType.SUPPLY_CHAIN,
        instruments=[ticker],
        provenance=Provenance(
            source=_SOURCE,
            source_id=accession,
            event_time=filed,
            ingest_time=now,
            url=url,
        ),
        relevance_score=min(1.0, float(pct) / 50),
        payload={
            "summary": summary,
            "factor": "supply_chain",
            "direction": "neutral",  # dependency context — not a thesis seed
            "revenue_pct": str(pct),
            "excerpt": excerpt,
            "form": "10-K",
            "accession": accession,
        },
    )
    return EventEnvelope(
        event_type=EventType.SIGNAL_CREATED,
        source=_SOURCE,
        event_time=filed,
        ingest_time=now,
        payload=signal.model_dump(mode="json"),
    )
