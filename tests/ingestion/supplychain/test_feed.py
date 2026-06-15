"""
Tests for SupplyChainFeed: per-watched-equity 10-K dependency extraction.

httpx.MockTransport routes by URL to the SEC ticker map, the submissions API,
and the 10-K document.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType
from ingestion.supplychain.feed import SupplyChainFeed
from ingestion.supplychain.settings import SupplyChainSettings

_TICKERS = json.dumps({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})

_ACCESSION = "0000320193-26-000010"
_PRIMARY = "aapl-20260101.htm"

_SUBMISSIONS = json.dumps({
    "filings": {
        "recent": {
            "form": ["8-K", "10-K", "10-Q"],
            "accessionNumber": ["x-1", _ACCESSION, "x-2"],
            "primaryDocument": ["a.htm", _PRIMARY, "b.htm"],
            "filingDate": ["2026-02-01", "2026-01-15", "2025-11-01"],
        }
    }
})

_TENK = (
    "<html><body><p>Customer A accounted for 23% of our net revenue "
    "in fiscal 2025.</p></body></html>"
)


def _transport(submissions: str = _SUBMISSIONS, tenk: str = _TENK) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "company_tickers.json" in url:
            return httpx.Response(200, text=_TICKERS)
        if "data.sec.gov/submissions" in url:
            return httpx.Response(200, text=submissions)
        if "/Archives/edgar/data/" in url:
            return httpx.Response(200, text=tenk)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _settings() -> SupplyChainSettings:
    return SupplyChainSettings(lookback_days=100_000, min_revenue_pct=Decimal("10"))


def _watchlist(instruments: dict[str, str]) -> MagicMock:
    wl = MagicMock()
    wl.active_instruments = frozenset(instruments)
    wl.get_market = lambda i: instruments.get(i, "crypto")
    return wl


@pytest.fixture
async def bus() -> AsyncIterator[InProcessBus]:
    b = InProcessBus(InMemoryEventStore())
    yield b
    await b.close()


async def _collect(bus: InProcessBus) -> list[EventEnvelope]:
    received: list[EventEnvelope] = []

    async def handler(env: EventEnvelope) -> None:
        received.append(env)

    await bus.subscribe(EventType.SIGNAL_CREATED, handler)
    return received


async def test_publishes_dependency_for_watched_equity(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = SupplyChainFeed(bus, _watchlist({"AAPL": "equity"}), _settings(), transport=_transport())

    await feed._poll()

    assert len(received) == 1
    assert received[0].payload["type"] == "supply_chain"
    assert received[0].payload["instruments"] == ["AAPL"]
    assert received[0].payload["payload"]["revenue_pct"] == "23"


async def test_crypto_only_watchlist_is_inert(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = SupplyChainFeed(
        bus, _watchlist({"BTC-USD": "crypto"}), _settings(), transport=_transport()
    )

    await feed._poll()

    assert received == []


async def test_second_poll_dedups(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = SupplyChainFeed(bus, _watchlist({"AAPL": "equity"}), _settings(), transport=_transport())

    await feed._poll()
    await feed._poll()

    assert len(received) == 1


async def test_old_10k_skipped_by_lookback(bus: InProcessBus) -> None:
    old = json.dumps({
        "filings": {
            "recent": {
                "form": ["10-K"],
                "accessionNumber": [_ACCESSION],
                "primaryDocument": [_PRIMARY],
                "filingDate": ["2000-01-01"],
            }
        }
    })
    received = await _collect(bus)
    settings = SupplyChainSettings(lookback_days=30, min_revenue_pct=Decimal("10"))
    feed = SupplyChainFeed(
        bus, _watchlist({"AAPL": "equity"}), settings, transport=_transport(submissions=old)
    )

    await feed._poll()

    assert received == []
