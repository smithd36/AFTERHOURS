"""
Tests for InsiderFeed polling and deduplication.

Network is replaced by httpx.MockTransport — no real HTTP requests. The mock
serves the EDGAR Atom index for the browse-edgar URL and the full-submission
.txt for the filing URL derived from the index link.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType
from ingestion.insider.feed import InsiderFeed
from ingestion.insider.settings import InsiderFeedSettings

_ACCESSION = "0000320193-26-000080"

_ATOM = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Latest Filings</title>
  <entry>
    <title>4 - COOK TIMOTHY D (Reporting)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/320193/000032019326000080/{_ACCESSION}-index.htm"/>
    <updated>2026-06-11T18:30:00-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number={_ACCESSION}</id>
  </entry>
</feed>"""

_TXT = """<SEC-DOCUMENT>0000320193-26-000080.txt
<DOCUMENT>
<TYPE>4
<TEXT>
<XML>
<?xml version="1.0"?>
<ownershipDocument>
  <periodOfReport>2026-06-09</periodOfReport>
  <issuer><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
  <reportingOwner><reportingOwnerId><rptOwnerName>COOK TIMOTHY D</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><officerTitle>CEO</officerTitle></reportingOwnerRelationship></reportingOwner>
  <nonDerivativeTable><nonDerivativeTransaction>
    <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
    <transactionAmounts>
      <transactionShares><value>10000</value></transactionShares>
      <transactionPricePerShare><value>195.50</value></transactionPricePerShare>
      <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
    </transactionAmounts>
  </nonDerivativeTransaction></nonDerivativeTable>
</ownershipDocument>
</XML>
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>"""


def _transport(atom_status: int = 200, txt_status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "browse-edgar" in url:
            return httpx.Response(atom_status, text=_ATOM)
        if url.endswith(".txt"):
            return httpx.Response(txt_status, text=_TXT)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _settings() -> InsiderFeedSettings:
    return InsiderFeedSettings(min_transaction_usd=Decimal("100000"))


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


async def test_publishes_material_filing(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = InsiderFeed(bus, _settings(), transport=_transport())

    await feed._poll()

    assert len(received) == 1
    assert received[0].payload["instruments"] == ["AAPL"]
    assert received[0].payload["provenance"]["source_id"] == _ACCESSION


async def test_second_poll_dedups(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = InsiderFeed(bus, _settings(), transport=_transport())

    await feed._poll()
    await feed._poll()

    assert len(received) == 1


async def test_initial_seen_suppresses(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = InsiderFeed(bus, _settings(), initial_seen={_ACCESSION}, transport=_transport())

    await feed._poll()

    assert received == []


async def test_index_http_error_no_raise(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = InsiderFeed(bus, _settings(), transport=_transport(atom_status=500))

    await feed._poll()  # must not raise — fetch failures are logged

    assert received == []


async def test_doc_fetch_error_left_unseen_for_retry(bus: InProcessBus) -> None:
    received = await _collect(bus)
    feed = InsiderFeed(bus, _settings(), transport=_transport(txt_status=500))

    await feed._poll()
    assert received == []
    # Accession not marked seen on a transient doc failure → retried next poll.
    feed._transport = _transport()  # now the .txt fetch succeeds
    await feed._poll()
    assert len(received) == 1
