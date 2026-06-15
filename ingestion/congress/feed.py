"""
Quiver Quantitative congressional-trading feed (STOCK Act disclosures).

Polls the Quiver `congresstrading` endpoint every `poll_interval_seconds` and
publishes signal.created for each new material trade (see CongressNormalizer).

Like EquityFeed, the feed no-ops without a token (`QUIVER_API_TOKEN`): it logs a
warning and idles, so it is safe to wire in unconditionally and stays free until
a token is supplied. Emits for ALL material trades market-wide — the
ThesisGenerator watchlist gate keeps it enrich-only (ADR-010 Phase 6A).

Cross-restart dedup: the caller seeds `initial_seen` with the composite keys of
congress signals already in the event store. Quiver has no per-row id, so the key
is composed from the row fields (see normalizer.dedup_key).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

import httpx
import structlog

from core.bus.base import Bus
from ingestion.health import FeedHealth

from .normalizer import CongressNormalizer, dedup_key
from .settings import CongressFeedSettings

logger = structlog.get_logger(__name__)

_SEEN_CAP = 20_000  # evict oldest when the dedup set exceeds this


class CongressFeed:
    """Polls Quiver for congressional trades and publishes signal.created."""

    def __init__(
        self,
        bus: Bus,
        settings: CongressFeedSettings | None = None,
        initial_seen: Iterable[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._bus = bus
        self._settings = settings or CongressFeedSettings()
        self._health = FeedHealth(bus, "congress")
        self._normalizer = CongressNormalizer(self._settings)
        self._transport = transport  # injectable for tests (httpx.MockTransport)
        # Ordered dict as an ordered set; oldest evicted at _SEEN_CAP.
        self._seen: dict[str, None] = dict.fromkeys(initial_seen or ())

    async def run(self) -> None:
        if not self._settings.api_token:
            logger.warning(
                "congress_feed.no_op",
                reason="QUIVER_API_TOKEN not set; congress signals disabled",
            )
            await self._health.report_degraded("disabled: QUIVER_API_TOKEN not set")
            while True:
                await asyncio.sleep(3600)

        try:
            await self._poll()
        except Exception:
            logger.exception("congress_feed.poll_error")
        logger.info("congress_feed.ready", seeded=len(self._seen))

        while True:
            await asyncio.sleep(self._settings.poll_interval_seconds)
            try:
                await self._poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("congress_feed.poll_error")

    async def _poll(self) -> None:
        headers = {
            "Authorization": f"Token {self._settings.api_token}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(
            timeout=20.0, headers=headers, transport=self._transport
        ) as client:
            try:
                resp = await client.get(self._settings.base_url)
                resp.raise_for_status()
                rows = resp.json()
                await self._health.report_healthy()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("congress_feed.fetch_failed", error=str(exc))
                await self._health.report_degraded(str(exc))
                return

        if not isinstance(rows, list):
            logger.warning("congress_feed.unexpected_payload")
            return

        new_count = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = dedup_key(row)
            if key in self._seen:
                continue
            self._mark_seen(key)
            envelope = self._normalizer.normalize(row)
            if envelope is not None:
                await self._bus.publish(envelope)
                new_count += 1

        if new_count:
            logger.info("congress_feed.published", count=new_count)

    def _mark_seen(self, key: str) -> None:
        self._seen[key] = None
        if len(self._seen) > _SEEN_CAP:
            del self._seen[next(iter(self._seen))]
