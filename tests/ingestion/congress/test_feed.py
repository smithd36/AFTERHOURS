"""
Tests for CongressFeed polling and deduplication.

Network is replaced by httpx.MockTransport — no real HTTP requests.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx
import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType
from ingestion.congress.feed import CongressFeed
from ingestion.congress.normalizer import dedup_key
from ingestion.congress.settings import CongressFeedSettings

# First row is material ($1M low); second is sub-threshold ($1,001 low) → dropped.
_ROWS: list[dict[str, Any]] = [
    {
        "Representative": "Nancy Pelosi",
        "Ticker": "NVDA",
        "Transaction": "Purchase",
        "Range": "$1,000,001 - $5,000,000",
        "House": "Representatives",
        "TransactionDate": "2026-05-01",
        "ReportDate": "2026-06-10",
    },
    {
        "Representative": "John Doe",
        "Ticker": "AAPL",
        "Transaction": "Sale",
        "Range": "$1,001 - $15,000",
        "House": "Senate",
        "TransactionDate": "2026-05-02",
        "ReportDate": "2026-06-11",
    },
]


def _transport(rows: list[dict[str, Any]] | None = None, status: int = 200) -> httpx.MockTransport:
    body = json.dumps(_ROWS if rows is None else rows)
    return httpx.MockTransport(lambda request: httpx.Response(status, text=body))


def _settings() -> CongressFeedSettings:
    return CongressFeedSettings(api_token="test-token", min_amount_usd=Decimal("50000"))


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


async def test_publishes_only_material_rows(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = CongressFeed(bus, _settings(), transport=_transport())

    await feed._poll()

    assert len(received) == 1  # NVDA buy; AAPL sub-threshold dropped
    assert received[0].payload["instruments"] == ["NVDA"]


async def test_second_poll_dedups(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = CongressFeed(bus, _settings(), transport=_transport())

    await feed._poll()
    await feed._poll()

    assert len(received) == 1


async def test_initial_seen_suppresses(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = CongressFeed(
        bus, _settings(), initial_seen={dedup_key(_ROWS[0])}, transport=_transport()
    )

    await feed._poll()

    assert received == []


async def test_http_error_no_raise(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = CongressFeed(bus, _settings(), transport=_transport(status=500))

    await feed._poll()  # must not raise — fetch failures are logged

    assert received == []
