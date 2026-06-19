"""
Tests for NewsFeed polling and deduplication.

Network is replaced by httpx.MockTransport — no real HTTP requests.
"""

from __future__ import annotations

import httpx
import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType
from ingestion.news.feed import NewsFeed
from ingestion.news.settings import NewsFeedSettings

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test Feed</title>
<item>
  <title>Bitcoin rallies past resistance</title>
  <link>https://example.com/a1</link>
  <description>BTC strength continues</description>
</item>
<item>
  <title>Ethereum upgrade ships</title>
  <link>https://example.com/a2</link>
  <description>ETH devs deliver</description>
</item>
</channel></rss>"""

_EMPTY_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Empty</title></channel></rss>"""


def _transport(body: str = _RSS, status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, text=body))


def _settings() -> NewsFeedSettings:
    return NewsFeedSettings(feed_urls=["https://example.com/rss"])


@pytest.fixture
async def bus():
    store = InMemoryEventStore()
    b = InProcessBus(store)
    yield b
    await b.close()


async def _collect(bus: InProcessBus) -> list[EventEnvelope]:
    received: list[EventEnvelope] = []

    async def handler(env: EventEnvelope) -> None:
        received.append(env)

    await bus.subscribe(EventType.SIGNAL_CREATED, handler)
    return received


class TestFirstPoll:
    async def test_cold_start_publishes_current_headlines(self, bus: InProcessBus) -> None:
        received = await _collect(bus)
        feed = NewsFeed(bus, _settings(), transport=_transport())

        await feed._poll()

        assert len(received) == 2
        titles = {e.payload["payload"]["title"] for e in received}
        assert "Bitcoin rallies past resistance" in titles

    async def test_initial_seen_suppresses_known_links(self, bus: InProcessBus) -> None:
        received = await _collect(bus)
        feed = NewsFeed(
            bus,
            _settings(),
            initial_seen={"https://example.com/a1"},
            transport=_transport(),
        )

        await feed._poll()

        assert len(received) == 1
        assert received[0].payload["provenance"]["source_id"] == "https://example.com/a2"


class _FakeWatchlist:
    """Empty watchlist: nothing is "watched", so the old filter dropped all."""

    @property
    def active_instruments(self) -> frozenset[str]:
        return frozenset()

    def get_market(self, instrument: str) -> str:
        return "crypto"


class TestUnwatchedNews:
    async def test_named_unwatched_news_still_publishes(self, bus: InProcessBus) -> None:
        # Discovery substrate (ADR-012): BTC/ETH headlines resolve to instruments
        # the watchlist doesn't hold; they must persist, not be dropped at ingest.
        received = await _collect(bus)
        feed = NewsFeed(
            bus, _settings(), transport=_transport(), watchlist=_FakeWatchlist()  # type: ignore[arg-type]
        )

        await feed._poll()

        assert len(received) == 2


class TestRepeatPoll:
    async def test_second_poll_publishes_nothing_new(self, bus: InProcessBus) -> None:
        received = await _collect(bus)
        feed = NewsFeed(bus, _settings(), transport=_transport())

        await feed._poll()
        await feed._poll()

        assert len(received) == 2  # no duplicates


class TestFailureModes:
    async def test_empty_feed_publishes_nothing(self, bus: InProcessBus) -> None:
        received = await _collect(bus)
        feed = NewsFeed(bus, _settings(), transport=_transport(body=_EMPTY_RSS))

        await feed._poll()

        assert received == []

    async def test_http_error_publishes_nothing(self, bus: InProcessBus) -> None:
        received = await _collect(bus)
        feed = NewsFeed(bus, _settings(), transport=_transport(status=500))

        await feed._poll()  # must not raise — fetch failures are logged

        assert received == []
