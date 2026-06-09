"""Portfolio snapshot endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("")
async def get_portfolio(request: Request) -> dict:
    portfolio = request.app.state.portfolio
    return portfolio.snapshot()


@router.post("/positions/{instrument}/close")
async def close_position(instrument: str, request: Request) -> dict:
    executor = request.app.state.executor
    ok = await executor.close_position(instrument)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No open position for {instrument}")
    return {"status": "closing", "instrument": instrument}
