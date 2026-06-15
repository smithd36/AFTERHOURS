"""
Government-exposure feed: lobbying (Senate LDA) + contracts (USASpending).

For each watched EQUITY instrument it resolves the company name, queries both
APIs by that name, and publishes signal.created for material, recent
filings/awards. Per-watched-name (not market-wide) because the sources are
name-keyed — see settings docstring.

Both sources are free; the feed only makes calls when the watchlist holds equity
instruments (a crypto-only watchlist is inert). Failures per source/ticker are
swallowed and logged — a downed gov source never affects price feeds or
positions.

Cross-restart dedup: the caller seeds `initial_seen` with the source_ids
(LDA filing_uuid / USASpending award id) already in the event store.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from core.bus.base import Bus
from ingestion.health import FeedHealth

from .normalizer import normalize_contract, normalize_lobbying
from .resolver import TickerNameResolver
from .settings import GovExposureSettings

if TYPE_CHECKING:
    from watchlist.manager import WatchlistManager

logger = structlog.get_logger(__name__)

_SEEN_CAP = 20_000
_PAGE_SIZE = 20
_CONTRACT_AWARD_TYPES = ["A", "B", "C", "D"]  # definitive/IDV contracts
_CONTRACT_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Base Obligation Date",
    "Awarding Agency",
    "Description",
    "generated_internal_id",
]


class GovExposureFeed:
    def __init__(
        self,
        bus: Bus,
        watchlist: WatchlistManager,
        settings: GovExposureSettings | None = None,
        initial_seen: Iterable[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._bus = bus
        self._watchlist = watchlist
        self._settings = settings or GovExposureSettings()
        # Two sub-sources, two health reporters: a USASpending outage stays
        # visible even while Senate-LDA is fine (the failure mode that prompted
        # this surface — every USASpending request 400'd while lobbying worked).
        self._health_lda = FeedHealth(bus, "lobbying")
        self._health_contracts = FeedHealth(bus, "gov_contracts")
        self._resolver = TickerNameResolver(
            self._settings.sec_tickers_url, self._settings.user_agent
        )
        self._transport = transport
        self._seen: dict[str, None] = dict.fromkeys(initial_seen or ())

    async def run(self) -> None:
        try:
            await self._poll()
        except Exception:
            logger.exception("govexposure.poll_error")
        logger.info("govexposure.ready", seeded=len(self._seen))

        while True:
            await asyncio.sleep(self._settings.poll_interval_seconds)
            try:
                await self._poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("govexposure.poll_error")

    async def _poll(self) -> None:
        equities = [
            i
            for i in self._watchlist.active_instruments
            if self._watchlist.get_market(i) == "equity"
        ]
        if not equities:
            return

        cutoff = datetime.now(UTC) - timedelta(days=self._settings.lookback_days)
        async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
            for ticker in equities:
                name = await self._resolver.name_for(client, ticker)
                if not name:
                    continue
                await self._poll_lobbying(client, ticker, name, cutoff)
                await self._poll_contracts(client, ticker, name, cutoff)
        await self._health_lda.commit()
        await self._health_contracts.commit()

    # ------------------------------------------------------------------

    async def _poll_lobbying(
        self, client: httpx.AsyncClient, ticker: str, name: str, cutoff: datetime
    ) -> None:
        headers = {"Accept": "application/json"}
        if self._settings.lda_api_key:
            headers["Authorization"] = f"Token {self._settings.lda_api_key}"
        try:
            resp = await client.get(
                self._settings.lda_url,
                params={"client_name": name, "ordering": "-dt_posted", "page_size": _PAGE_SIZE},
                headers=headers,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            self._health_lda.fetch_ok()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("govexposure.lda_fetch_failed", ticker=ticker, error=str(exc))
            self._health_lda.fetch_failed(str(exc))
            return

        for filing in results:
            if not isinstance(filing, dict):
                continue
            uid = str(filing.get("filing_uuid") or "")
            if not uid or uid in self._seen:
                continue
            self._mark_seen(uid)
            env = normalize_lobbying(filing, ticker, self._settings.min_lobbying_usd)
            if env is not None and env.event_time >= cutoff:
                await self._bus.publish(env)

    async def _poll_contracts(
        self, client: httpx.AsyncClient, ticker: str, name: str, cutoff: datetime
    ) -> None:
        today = datetime.now(UTC).date()
        start = today - timedelta(days=self._settings.lookback_days)
        body: dict[str, Any] = {
            "filters": {
                "recipient_search_text": [name],
                "award_type_codes": _CONTRACT_AWARD_TYPES,
                "time_period": [
                    {"start_date": start.isoformat(), "end_date": today.isoformat()}
                ],
            },
            "fields": _CONTRACT_FIELDS,
            "sort": "Base Obligation Date",
            "order": "desc",
            "limit": _PAGE_SIZE,
        }
        try:
            resp = await client.post(self._settings.usaspending_url, json=body)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            self._health_contracts.fetch_ok()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("govexposure.usaspending_fetch_failed", ticker=ticker, error=str(exc))
            self._health_contracts.fetch_failed(str(exc))
            return

        for award in results:
            if not isinstance(award, dict):
                continue
            aid = str(award.get("generated_internal_id") or award.get("Award ID") or "")
            if not aid or aid in self._seen:
                continue
            self._mark_seen(aid)
            env = normalize_contract(award, ticker, self._settings.min_contract_usd)
            if env is not None and env.event_time >= cutoff:
                await self._bus.publish(env)

    def _mark_seen(self, key: str) -> None:
        self._seen[key] = None
        if len(self._seen) > _SEEN_CAP:
            del self._seen[next(iter(self._seen))]
