"""
Supply-chain feed: 10-K customer-concentration dependencies from SEC EDGAR.

For each watched EQUITY it resolves the CIK, finds the latest 10-K via the
submissions API, fetches the primary document, and publishes a signal.created if
a material customer-concentration disclosure is present (see extractor). Free, no
API key; inert on a crypto-only watchlist. Per-watched-name (the data is
company-keyed), so enrich-only by construction.

Cross-restart dedup: the caller seeds `initial_seen` with the 10-K accession
numbers already in the event store.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import structlog

from core.bus.base import Bus
from ingestion.health import FeedHealth

from .extractor import build_signal, strip_html
from .resolver import TickerCikResolver
from .settings import SupplyChainSettings

if TYPE_CHECKING:
    from watchlist.manager import WatchlistManager

logger = structlog.get_logger(__name__)

_SEEN_CAP = 10_000


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class SupplyChainFeed:
    def __init__(
        self,
        bus: Bus,
        watchlist: WatchlistManager,
        settings: SupplyChainSettings | None = None,
        initial_seen: Iterable[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._bus = bus
        self._watchlist = watchlist
        self._settings = settings or SupplyChainSettings()
        self._health = FeedHealth(bus, "supply_chain")
        self._resolver = TickerCikResolver(
            self._settings.sec_tickers_url, self._settings.user_agent
        )
        self._transport = transport
        self._headers = {"User-Agent": self._settings.user_agent}
        self._seen: dict[str, None] = dict.fromkeys(initial_seen or ())

    async def run(self) -> None:
        try:
            await self._poll()
        except Exception:
            logger.exception("supplychain.poll_error")
        logger.info("supplychain.ready", seeded=len(self._seen))

        while True:
            await asyncio.sleep(self._settings.poll_interval_seconds)
            try:
                await self._poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("supplychain.poll_error")

    async def _poll(self) -> None:
        equities = [
            i
            for i in self._watchlist.active_instruments
            if self._watchlist.get_market(i) == "equity"
        ]
        if not equities:
            return

        cutoff = datetime.now(UTC) - timedelta(days=self._settings.lookback_days)
        async with httpx.AsyncClient(timeout=60.0, transport=self._transport) as client:
            new_count = 0
            for ticker in equities:
                cik = await self._resolver.cik_for(client, ticker)
                if cik is None:
                    continue
                if await self._process_ticker(client, ticker, cik, cutoff):
                    new_count += 1
            if new_count:
                logger.info("supplychain.published", count=new_count)
        await self._health.commit()

    async def _process_ticker(
        self, client: httpx.AsyncClient, ticker: str, cik: int, cutoff: datetime
    ) -> bool:
        info = await self._latest_10k(client, cik)
        if info is None:
            return False
        accession, primary_doc, filed = info
        if not accession or not primary_doc or filed is None or accession in self._seen:
            return False
        if filed < cutoff:
            self._mark_seen(accession)  # current 10-K is older than the window
            return False

        doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{accession.replace('-', '')}/{primary_doc}"
        )
        try:
            doc = await client.get(doc_url, headers=self._headers)
            doc.raise_for_status()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("supplychain.doc_fetch_failed", ticker=ticker, error=str(exc))
            return False  # left unseen → retried next poll

        self._mark_seen(accession)
        env = build_signal(
            strip_html(doc.text), ticker, filed, accession, doc_url, self._settings.min_revenue_pct
        )
        if env is None:
            return False
        await self._bus.publish(env)
        return True

    async def _latest_10k(
        self, client: httpx.AsyncClient, cik: int
    ) -> tuple[str, str, datetime | None] | None:
        url = self._settings.submissions_url.format(cik=cik)
        try:
            resp = await client.get(url, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()
            self._health.fetch_ok()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("supplychain.submissions_fetch_failed", cik=cik, error=str(exc))
            self._health.fetch_failed(str(exc))
            return None

        recent = (data.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accessions = recent.get("accessionNumber") or []
        docs = recent.get("primaryDocument") or []
        dates = recent.get("filingDate") or []
        for i, form in enumerate(forms):
            if form != "10-K":
                continue
            try:
                return accessions[i], docs[i], _parse_date(dates[i])
            except IndexError:
                return None
        return None

    def _mark_seen(self, accession: str) -> None:
        self._seen[accession] = None
        if len(self._seen) > _SEEN_CAP:
            del self._seen[next(iter(self._seen))]
