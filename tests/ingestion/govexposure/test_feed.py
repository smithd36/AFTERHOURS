"""
Tests for GovExposureFeed: per-watched-equity lobbying + contract polling.

Network is replaced by httpx.MockTransport, routing by URL to the SEC ticker
map, Senate LDA, and USASpending. lookback_days is set huge so the fixed
fixture dates always clear the recency cutoff regardless of wall clock.
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
from ingestion.govexposure.feed import GovExposureFeed
from ingestion.govexposure.settings import GovExposureSettings

_TICKERS = json.dumps({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})

_LDA = json.dumps({
    "results": [{
        "filing_uuid": "lda-1",
        "income": "120000.00",
        "dt_posted": "2026-06-10T12:00:00Z",
        "filing_year": 2026,
        "client": {"name": "Apple Inc."},
        "registrant": {"name": "Big Lobby LLC"},
        "lobbying_activities": [{"general_issue_code_display": "Taxation"}],
    }]
})

_USASPENDING = json.dumps({
    "results": [{
        "generated_internal_id": "ct-1",
        "Recipient Name": "Apple Inc.",
        "Award Amount": 5_000_000,
        "Base Obligation Date": "2026-06-09",
        "Awarding Agency": "Department of Defense",
        "Description": "Logistics support",
    }]
})


def _transport(lda: str = _LDA, usaspending: str = _USASPENDING) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "company_tickers.json" in url:
            return httpx.Response(200, text=_TICKERS)
        if "lda.senate.gov" in url:
            return httpx.Response(200, text=lda)
        if "usaspending" in url:
            return httpx.Response(200, text=usaspending)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _settings() -> GovExposureSettings:
    return GovExposureSettings(
        lookback_days=100_000,
        min_lobbying_usd=Decimal("50000"),
        min_contract_usd=Decimal("1000000"),
    )


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


async def test_publishes_lobbying_and_contract_for_watched_equity(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = GovExposureFeed(bus, _watchlist({"AAPL": "equity"}), _settings(), transport=_transport())

    await feed._poll()

    types = sorted(e.payload["type"] for e in received)
    assert types == ["gov_contract", "lobbying"]
    assert all(e.payload["instruments"] == ["AAPL"] for e in received)


async def test_crypto_only_watchlist_is_inert(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = GovExposureFeed(
        bus, _watchlist({"BTC-USD": "crypto"}), _settings(), transport=_transport()
    )

    await feed._poll()

    assert received == []


async def test_second_poll_dedups(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = GovExposureFeed(bus, _watchlist({"AAPL": "equity"}), _settings(), transport=_transport())

    await feed._poll()
    await feed._poll()

    assert len(received) == 2


async def test_initial_seen_suppresses(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = GovExposureFeed(
        bus,
        _watchlist({"AAPL": "equity"}),
        _settings(),
        initial_seen={"lda-1", "ct-1"},
        transport=_transport(),
    )

    await feed._poll()

    assert received == []
