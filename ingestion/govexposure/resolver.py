"""
Ticker → company-name resolver, backed by SEC's free company_tickers.json.

Lobbying and contract data are keyed by company name, not ticker; this maps the
watchlist's tickers to the legal names those APIs search on. The map is fetched
once and cached. On fetch failure the cache stays unset so the next poll retries
(a transient SEC outage just means no gov-exposure signals that cycle).
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class TickerNameResolver:
    def __init__(self, url: str, user_agent: str) -> None:
        self._url = url
        self._user_agent = user_agent
        self._map: dict[str, str] | None = None

    async def name_for(self, client: httpx.AsyncClient, ticker: str) -> str | None:
        if self._map is None:
            await self._load(client)
        if not self._map:
            return None
        return self._map.get(ticker.upper())

    async def _load(self, client: httpx.AsyncClient) -> None:
        try:
            resp = await client.get(self._url, headers={"User-Agent": self._user_agent})
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except Exception:
            logger.warning("govexposure.ticker_map_load_failed")
            return  # leave cache unset → retried next poll
        # data is {"0": {"cik_str": .., "ticker": "AAPL", "title": "Apple Inc."}, ...}
        self._map = {
            str(row["ticker"]).upper(): str(row["title"])
            for row in data.values()
            if isinstance(row, dict) and row.get("ticker") and row.get("title")
        }
        logger.info("govexposure.ticker_map_loaded", count=len(self._map))
