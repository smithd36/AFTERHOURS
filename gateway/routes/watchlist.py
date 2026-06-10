from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from watchlist import WatchlistManager

router = APIRouter()


class AddInstrumentRequest(BaseModel):
    instrument: str
    market: str = "crypto"


@router.get("/api/watchlist")
async def get_watchlist(request: Request) -> dict:
    manager: WatchlistManager = request.app.state.watchlist_manager
    entries = await manager.list_entries()
    return {
        "instruments": [
            {"instrument": e.instrument, "market": e.market, "added_at": e.added_at.isoformat()}
            for e in entries
        ]
    }


@router.post("/api/watchlist", status_code=201)
async def add_instrument(body: AddInstrumentRequest, request: Request) -> dict:
    manager: WatchlistManager = request.app.state.watchlist_manager
    instrument = body.instrument.strip().upper()
    if not instrument:
        raise HTTPException(status_code=422, detail="instrument must not be empty")
    await manager.add(instrument, body.market)
    return {"instrument": instrument, "market": body.market, "status": "added"}


@router.delete("/api/watchlist/{instrument}", status_code=200)
async def remove_instrument(instrument: str, request: Request) -> dict:
    manager: WatchlistManager = request.app.state.watchlist_manager
    instrument = instrument.upper()
    if instrument not in manager.active_instruments:
        raise HTTPException(status_code=404, detail=f"{instrument} not in watchlist")
    await manager.remove(instrument)
    return {"instrument": instrument, "status": "removed"}
