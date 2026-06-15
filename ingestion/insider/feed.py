"""
SEC EDGAR Form 4 (insider transactions) feed.

Polls the EDGAR "latest filings" Atom feed for recent Form 4s every
`poll_interval_seconds`, fetches each new filing's full submission, extracts the
ownership XML, and publishes signal.created for material open-market trades (see
Form4Normalizer).

Emits for ALL material filings market-wide, not just watched instruments: the
bus persists them (audit) and the ThesisGenerator's watchlist gate decides which
ones actually drive a thesis (enrich-only — ADR-010 Phase 6A). Unwatched-ticker
filings sit in the event store as the substrate for Phase 6B auto-discovery.

Cross-restart dedup: the caller seeds `initial_seen` with accession numbers of
insider signals already in the event store.
"""

from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, datetime

import httpx
import structlog

from core.bus.base import Bus
from ingestion.health import FeedHealth

from .normalizer import Form4Normalizer
from .settings import InsiderFeedSettings

logger = structlog.get_logger(__name__)

_SEEN_CAP = 10_000  # evict oldest when the dedup set exceeds this
_ATOM = "{http://www.w3.org/2005/Atom}"
_OWNERSHIP_RE = re.compile(r"<ownershipDocument>.*?</ownershipDocument>", re.DOTALL)


class InsiderFeed:
    """Polls EDGAR for Form 4 filings and publishes signal.created for material trades."""

    def __init__(
        self,
        bus: Bus,
        settings: InsiderFeedSettings | None = None,
        initial_seen: Iterable[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._bus = bus
        self._settings = settings or InsiderFeedSettings()
        self._health = FeedHealth(bus, "insider")
        self._normalizer = Form4Normalizer(self._settings)
        self._transport = transport  # injectable for tests (httpx.MockTransport)
        self._headers = {"User-Agent": self._settings.user_agent}
        # Ordered dict as an ordered set: insertion order = arrival order;
        # oldest accession is evicted at _SEEN_CAP.
        self._seen: dict[str, None] = dict.fromkeys(initial_seen or ())

    async def run(self) -> None:
        try:
            await self._poll()
        except Exception:
            logger.exception("insider_feed.poll_error")
        logger.info("insider_feed.ready", seeded=len(self._seen))

        while True:
            await asyncio.sleep(self._settings.poll_interval_seconds)
            try:
                await self._poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("insider_feed.poll_error")

    async def _poll(self) -> None:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=self._headers,
            transport=self._transport,
        ) as client:
            try:
                resp = await client.get(self._settings.current_url)
                resp.raise_for_status()
                await self._health.report_healthy()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("insider_feed.index_fetch_failed", error=str(exc))
                await self._health.report_degraded(str(exc))
                return

            new_count = 0
            for accession, href, accepted in self._parse_atom(resp.text):
                if not accession or accession in self._seen or "-index.htm" not in href:
                    continue
                txt_url = href.replace("-index.htm", ".txt")
                try:
                    doc = await client.get(txt_url)
                    doc.raise_for_status()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Transient: leave unseen so the next poll retries (until the
                    # filing scrolls off the getcurrent window).
                    logger.warning("insider_feed.doc_fetch_failed", url=txt_url, error=str(exc))
                    continue

                self._mark_seen(accession)
                match = _OWNERSHIP_RE.search(doc.text)
                if match is None:
                    continue
                envelope = self._normalizer.normalize(match.group(), accession, txt_url, accepted)
                if envelope is not None:
                    await self._bus.publish(envelope)
                    new_count += 1

            if new_count:
                logger.info("insider_feed.published", count=new_count)

    def _parse_atom(self, text: str) -> list[tuple[str, str, datetime]]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            logger.warning("insider_feed.atom_parse_failed")
            return []

        entries: list[tuple[str, str, datetime]] = []
        for entry in root.findall(f"{_ATOM}entry"):
            id_text = entry.findtext(f"{_ATOM}id") or ""
            accession = (
                id_text.split("accession-number=", 1)[1].strip()
                if "accession-number=" in id_text
                else ""
            )
            link = entry.find(f"{_ATOM}link")
            href = (link.get("href") or "") if link is not None else ""
            updated = entry.findtext(f"{_ATOM}updated") or ""
            try:
                accepted = datetime.fromisoformat(updated).astimezone(UTC)
            except (ValueError, TypeError):
                accepted = datetime.now(UTC)
            entries.append((accession, href, accepted))
        return entries

    def _mark_seen(self, accession: str) -> None:
        self._seen[accession] = None
        if len(self._seen) > _SEEN_CAP:
            del self._seen[next(iter(self._seen))]
