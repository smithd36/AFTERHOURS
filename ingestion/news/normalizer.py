"""
RSS/Atom entry → EventEnvelope(signal.created).

Instrument extraction uses simple keyword matching — no NLP. This is
intentionally conservative: a false negative (missing an instrument) is
safer than a false positive (associating news with the wrong asset).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from core.schemas.common import Provenance
from core.schemas.events import EventEnvelope, EventType
from core.schemas.signal import Signal, SignalType

# lowercase keyword → canonical symbol
_KEYWORDS: dict[str, str] = {
    "bitcoin": "BTC-USD",
    "btc": "BTC-USD",
    "ethereum": "ETH-USD",
    "eth": "ETH-USD",
    "solana": "SOL-USD",
    "sol": "SOL-USD",
    "ripple": "XRP-USD",
    "xrp": "XRP-USD",
    "cardano": "ADA-USD",
    "ada": "ADA-USD",
    "dogecoin": "DOGE-USD",
    "doge": "DOGE-USD",
    "litecoin": "LTC-USD",
    "ltc": "LTC-USD",
    "chainlink": "LINK-USD",
    "avax": "AVAX-USD",
    "avalanche": "AVAX-USD",
    "polkadot": "DOT-USD",
}

_MAX_SUMMARY = 500
_HTML_TAG = re.compile(r"<[^>]+>")
_DOMAIN = re.compile(r"https?://(?:www\.)?([^/]+)")
_WORD = re.compile(r"\b\w+\b")


class NewsNormalizer:
    """Converts a single feedparser entry dict into an EventEnvelope or None."""

    def normalize(self, entry: dict[str, Any]) -> EventEnvelope | None:
        title: str = (entry.get("title") or "").strip()
        link: str = (entry.get("link") or "").strip()
        if not title or not link:
            return None

        event_time = self._parse_date(entry)
        now = datetime.now(UTC)

        raw = entry.get("summary") or entry.get("description") or ""
        summary = _HTML_TAG.sub(" ", raw).strip()[:_MAX_SUMMARY]

        instruments = self._extract_instruments(f"{title} {summary}")
        domain_match = _DOMAIN.search(link)
        source_domain = domain_match.group(1) if domain_match else ""

        signal = Signal(
            type=SignalType.NEWS,
            instruments=instruments,
            provenance=Provenance(
                source="rss_news_feed",
                source_id=link,
                event_time=event_time,
                ingest_time=now,
                url=link,
            ),
            payload={
                "title": title,
                "summary": summary,
                "source_domain": source_domain,
            },
        )
        return EventEnvelope(
            event_type=EventType.SIGNAL_CREATED,
            source="rss_news_feed",
            event_time=event_time,
            ingest_time=now,
            payload=signal.model_dump(mode="json"),
        )

    @staticmethod
    def _parse_date(entry: dict[str, Any]) -> datetime:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                pass
        return datetime.now(UTC)

    @staticmethod
    def _extract_instruments(text: str) -> list[str]:
        words = _WORD.findall(text.lower())
        found = {_KEYWORDS[w] for w in words if w in _KEYWORDS}
        return sorted(found)
