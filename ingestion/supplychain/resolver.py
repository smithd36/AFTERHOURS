"""
Ticker → CIK resolver, backed by SEC's free company_tickers.json.

The submissions API is keyed by CIK; this maps the watchlist's tickers to them.
Fetched once and cached; on failure the cache stays unset so the next poll
retries.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class TickerCikResolver:
    def __init__(self, url: str, user_agent: str) -> None:
        self._url = url
        self._user_agent = user_agent
        self._map: dict[str, int] | None = None

    async def cik_for(self, client: httpx.AsyncClient, ticker: str) -> int | None:
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
            logger.warning("supplychain.ticker_map_load_failed")
            return  # leave cache unset → retried next poll
        cik_map: dict[str, int] = {}
        for row in data.values():
            if not isinstance(row, dict) or not row.get("ticker") or row.get("cik_str") is None:
                continue
            try:
                cik_map[str(row["ticker"]).upper()] = int(row["cik_str"])
            except (TypeError, ValueError):
                continue
        self._map = cik_map
        logger.info("supplychain.ticker_map_loaded", count=len(self._map))
