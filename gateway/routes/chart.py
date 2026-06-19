"""Historical OHLC for the chart UI (ADR-012 Discover workspace, search-a-symbol).

On-demand pull: fetches bars from Kraken (crypto) or Alpaca (equity) for a named
range and returns one normalized shape. No state, no persistence — like analytics.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ingestion.history import RANGES, HistoryUnavailable, fetch_ohlc, is_crypto

router = APIRouter(prefix="/api/chart", tags=["chart"])


@router.get("/{instrument}")
async def get_chart(
    instrument: str,
    range_key: str = Query(default="3M", alias="range"),
) -> dict[str, Any]:
    symbol = instrument.strip().upper()
    if not symbol:
        raise HTTPException(status_code=422, detail="instrument required")
    if range_key not in RANGES:
        raise HTTPException(status_code=422, detail=f"range must be one of {list(RANGES)}")
    try:
        bars = await fetch_ohlc(symbol, range_key=range_key)
    except HistoryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "instrument": symbol,
        "market": "crypto" if is_crypto(symbol) else "equity",
        "range": range_key,
        "bars": [b.__dict__ for b in bars],
    }
