"""
RSS/Atom entry → EventEnvelope(signal.created).

Instrument extraction uses simple keyword matching — no NLP. This is
intentionally conservative: a false negative (missing an instrument) is
safer than a false positive (associating news with the wrong asset).

Two matchers run:
  * prose names → symbol (``_NAME_KEYWORDS``): all crypto, plus a small
    curated set of unambiguous equity brand names ("Tesla" → TSLA).
  * live-watchlist equity tickers as a cashtag ($TSLA) or a standalone
    all-caps token (TSLA). Case-sensitive uppercase so lowercase prose
    ("gilt") never matches a ticker (GILT).
The watchlist stores no company name, so most equities rely on the ticker
matcher. ponytail: curated name map + symbol match, no schema/network;
add an Alpaca name column only if real headlines slip through untagged.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.schemas.common import Provenance
from core.schemas.events import EventEnvelope, EventType
from core.schemas.signal import Signal, SignalType

if TYPE_CHECKING:
    from watchlist.manager import WatchlistManager

# lowercase name → canonical symbol. Multi-word names are matched as whole
# phrases. Equities are a curated high-confidence subset only — the ticker
# matcher below covers the rest of the watchlist. Extend as needed.
_NAME_KEYWORDS: dict[str, str] = {
    # crypto
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
    # equities — unambiguous brand names only ("amazon" can mis-hit the
    # rainforest; kept because AMZN news value outweighs the rare collision).
    "tesla": "TSLA",
    "amazon": "AMZN",
    "nvidia": "NVDA",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "medtronic": "MDT",
    "blackberry": "BB",
    "rocket lab": "RKLB",
    "joby": "JOBY",
    "joby aviation": "JOBY",
    "archer aviation": "ACHR",
    "intuitive machines": "LUNR",
    "iridium": "IRDM",
}

# Precompiled whole-phrase matchers; searched against the lowercased text.
_NAME_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"\b{re.escape(name)}\b"), symbol)
    for name, symbol in _NAME_KEYWORDS.items()
]

_CASHTAG = re.compile(r"\$([A-Za-z]{1,6})\b")
_UPPER_TOKEN = re.compile(r"\b[A-Z]{1,6}\b")  # case-sensitive: prose stays unmatched

_MAX_SUMMARY = 500
_HTML_TAG = re.compile(r"<[^>]+>")
_DOMAIN = re.compile(r"https?://(?:www\.)?([^/]+)")


class NewsNormalizer:
    """Converts a single feedparser entry dict into an EventEnvelope or None."""

    def __init__(self, watchlist: WatchlistManager | None = None) -> None:
        self._watchlist = watchlist

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
                # Discovery-eligible (ADR-012): the `factor` tag makes news a
                # confluence contributor. News carries no reliable direction
                # without sentiment NLP, so it enters as damped-neutral context —
                # it can lift an unwatched name when it coincides with a
                # directional factor (e.g. an insider buy), never on its own.
                # ponytail: neutral default; add keyword sentiment only if news
                # ever needs to vote a direction of its own.
                "factor": "news",
                "direction": "neutral",
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

    def _extract_instruments(self, text: str) -> list[str]:
        lower = text.lower()
        found = {symbol for pattern, symbol in _NAME_PATTERNS if pattern.search(lower)}
        found.update(self._match_watchlist_tickers(text))
        return sorted(found)

    def _match_watchlist_tickers(self, text: str) -> set[str]:
        """Match live-watchlist equity tickers as $cashtags or all-caps tokens."""
        if self._watchlist is None:
            return set()
        equities = {
            s
            for s in self._watchlist.active_instruments
            if self._watchlist.get_market(s) == "equity"
        }
        if not equities:
            return set()
        candidates = {m.upper() for m in _CASHTAG.findall(text)}
        candidates.update(_UPPER_TOKEN.findall(text))
        return equities & candidates
