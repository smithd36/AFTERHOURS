"""
RSS/Atom news feed.

Polls each configured URL every `poll_interval_seconds` and publishes
signal.created for each headline not seen before.

Cross-restart deduplication: the caller seeds `initial_seen` with the
source ids (links) of news signals already in the event store. On the
first-ever run the store is empty, so the headlines currently in the
feeds are published immediately — the Signal Feed is never blank on a
cold start. On restarts only genuinely new items emit events.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import TYPE_CHECKING

import feedparser  # type: ignore[import-untyped]
import httpx
import structlog

from core.bus.base import Bus
from ingestion.health import FeedHealth

from .normalizer import NewsNormalizer
from .settings import NewsFeedSettings

if TYPE_CHECKING:
    from watchlist.manager import WatchlistManager

logger = structlog.get_logger(__name__)

_SEEN_CAP = 5_000  # evict oldest when the dedup set exceeds this

# Several publishers gate RSS on the User-Agent: with the default
# "python-httpx/x.y" UA, Yahoo returns 429 and Nasdaq/Benzinga tarpit the
# connection until it times out (surfacing as news_feed.fetch_failed). A
# browser-like UA gets a normal 200 + feed body from all of them.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
}


class NewsFeed:
    """Polls RSS feeds and publishes signal.created for each new headline."""

    def __init__(
        self,
        bus: Bus,
        settings: NewsFeedSettings | None = None,
        initial_seen: Iterable[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        watchlist: WatchlistManager | None = None,
    ) -> None:
        self._bus = bus
        self._settings = settings or NewsFeedSettings()
        self._health = FeedHealth(bus, "news")
        self._normalizer = NewsNormalizer(watchlist)
        self._transport = transport  # injectable for tests (httpx.MockTransport)
        # Ordered dict used as an ordered set: insertion order = arrival order.
        # Oldest entry is evicted when _SEEN_CAP is reached.
        self._seen: dict[str, None] = dict.fromkeys(initial_seen or ())

    async def run(self) -> None:
        try:
            await self._poll()
        except Exception:
            logger.exception("news_feed.poll_error")
        logger.info(
            "news_feed.ready",
            feeds=len(self._settings.feed_urls),
            seeded=len(self._seen),
        )

        while True:
            await asyncio.sleep(self._settings.poll_interval_seconds)
            try:
                await self._poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("news_feed.poll_error")

    async def _poll(self) -> None:
        # follow_redirects: some feeds (e.g. CoinDesk) sit behind a permanent
        # redirect; httpx does not follow redirects by default and a 3xx body
        # parses as an empty feed without ever raising.
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers=_HEADERS,
            transport=self._transport,
        ) as client:
            for url in self._settings.feed_urls:
                try:
                    await self._fetch(client, url)
                    self._health.fetch_ok()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("news_feed.fetch_failed", url=url, error=str(exc))
                    self._health.fetch_failed(str(exc))
            await self._health.commit()

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> None:
        resp = await client.get(url)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)

        if not parsed.entries:
            # A healthy feed always has entries; zero means a broken URL,
            # a non-feed response, or a parse failure — surface it.
            logger.warning(
                "news_feed.empty_feed",
                url=url,
                status_code=resp.status_code,
                bozo=bool(getattr(parsed, "bozo", False)),
            )
            return

        new_count = 0
        for entry in parsed.entries:
            link: str = (entry.get("link") or "").strip()
            if not link or link in self._seen:
                continue
            self._mark_seen(link)
            envelope = self._normalizer.normalize(entry)
            if envelope is not None:
                # Publish all named/general news unconditionally — named-but-
                # unwatched headlines are the substrate the discovery engine
                # (ADR-012) fuses into candidates, so they must persist, not be
                # dropped at ingest. The watchlist is still used by the
                # normalizer to match live tickers; the Signal Feed (which
                # already shows general market news) just shows a little more.
                await self._bus.publish(envelope)
                new_count += 1

        if new_count:
            logger.info("news_feed.published", url=url, count=new_count)

    def _mark_seen(self, link: str) -> None:
        self._seen[link] = None
        if len(self._seen) > _SEEN_CAP:
            oldest = next(iter(self._seen))
            del self._seen[oldest]
