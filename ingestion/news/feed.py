"""
RSS/Atom news feed.

Polls each configured URL every `poll_interval_seconds`. On startup it
marks all existing items as seen so restarts don't flood the bus with
historical headlines. Only genuinely new items emit signal.created events.
"""

from __future__ import annotations

import asyncio

import feedparser  # type: ignore[import-untyped]
import httpx
import structlog

from core.bus.base import Bus

from .normalizer import NewsNormalizer
from .settings import NewsFeedSettings

logger = structlog.get_logger(__name__)

_SEEN_CAP = 5_000  # evict oldest when the dedup set exceeds this


class NewsFeed:
    """Polls RSS feeds and publishes signal.created for each new headline."""

    def __init__(self, bus: Bus, settings: NewsFeedSettings | None = None) -> None:
        self._bus = bus
        self._settings = settings or NewsFeedSettings()
        self._normalizer = NewsNormalizer()
        # Ordered dict used as an ordered set: insertion order = arrival order.
        # Oldest entry is evicted when _SEEN_CAP is reached.
        self._seen: dict[str, None] = {}

    async def run(self) -> None:
        # Mark all currently-live items as seen before entering the publish loop.
        await self._poll(mark_only=True)
        logger.info("news_feed.ready", feeds=len(self._settings.feed_urls))

        while True:
            await asyncio.sleep(self._settings.poll_interval_seconds)
            try:
                await self._poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("news_feed.poll_error")

    async def _poll(self, mark_only: bool = False) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for url in self._settings.feed_urls:
                try:
                    await self._fetch(client, url, mark_only)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("news_feed.fetch_failed", url=url)

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        url: str,
        mark_only: bool,
    ) -> None:
        resp = await client.get(url)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)

        new_count = 0
        for entry in parsed.entries:
            link: str = (entry.get("link") or "").strip()
            if not link or link in self._seen:
                continue
            self._mark_seen(link)
            if mark_only:
                continue
            envelope = self._normalizer.normalize(entry)
            if envelope is not None:
                await self._bus.publish(envelope)
                new_count += 1

        if not mark_only and new_count:
            logger.info("news_feed.published", url=url, count=new_count)

    def _mark_seen(self, link: str) -> None:
        self._seen[link] = None
        if len(self._seen) > _SEEN_CAP:
            oldest = next(iter(self._seen))
            del self._seen[oldest]
