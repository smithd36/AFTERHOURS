"""Portfolio snapshot endpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request

from analytics import realized_pnl
from core.schemas.decision import Side
from portfolio.ledger import TRADING_TZ, trading_day

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


@router.get("/trades")
async def get_trades(
    request: Request,
    date: str | None = Query(default=None, description="UTC date (YYYY-MM-DD). Omit for today."),
) -> dict:
    """
    Returns all fills for a given UTC day.

    Omitting `date` returns today's trades from the in-memory ledger (fast, includes
    realized P&L for close fills). Passing a past date queries the event store and
    pairs open/close fills by decision_id to compute P&L.
    """
    portfolio = request.app.state.portfolio

    if date is None:
        today = trading_day(datetime.now(UTC))
        return {"date": str(today), "trades": portfolio.daily_trades}

    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    today = trading_day(datetime.now(UTC))
    if target == today:
        return {"date": str(today), "trades": portfolio.daily_trades}

    store = request.app.state.event_store
    # Bound the NYSE calendar day, matching the live ledger's rollover. A trade at
    # e.g. 21:00 ET (next UTC day) belongs to its ET session, not the UTC date.
    start = datetime(target.year, target.month, target.day, tzinfo=TRADING_TZ)
    end = start + timedelta(days=1)

    day_fills = await store.range(["order.filled"], start=start, end=end)

    # Build a lookup of open fills by decision_id for P&L computation on closes.
    # Open fills for a position closed on `target` may themselves be on a prior day,
    # so fetch them separately for any decision_ids not already in `day_fills`.
    open_fills: dict[str, dict] = {
        f.payload["decision_id"]: f.payload
        for f in day_fills
        if f.payload.get("action") == "open" and f.payload.get("decision_id")
    }
    missing_ids = {
        f.payload["decision_id"]
        for f in day_fills
        if f.payload.get("action") == "close"
        and f.payload.get("decision_id")
        and f.payload["decision_id"] not in open_fills
    }
    if missing_ids:
        all_fills = await store.range(["order.filled"])
        for f in all_fills:
            did = f.payload.get("decision_id", "")
            if f.payload.get("action") == "open" and did in missing_ids:
                open_fills[did] = f.payload

    trades = []
    for fill in day_fills:
        p = fill.payload
        realized_str: str | None = None
        if p.get("action") == "close":
            open_p = open_fills.get(p.get("decision_id", ""))
            if open_p:
                realized = realized_pnl(
                    side=Side(p.get("side", "long")),
                    entry_price=Decimal(str(open_p.get("fill_price", "0"))),
                    exit_price=Decimal(str(p.get("fill_price", "0"))),
                    quantity=Decimal(str(p.get("quantity", "0"))),
                    entry_fee=Decimal(str(open_p.get("fee", "0"))),
                    exit_fee=Decimal(str(p.get("fee", "0"))),
                )
                realized_str = str(realized)

        trades.append({
            "instrument": p.get("instrument", ""),
            "action": p.get("action", ""),
            "side": p.get("side", ""),
            "fill_price": p.get("fill_price", "0"),
            "quantity": p.get("quantity", "0"),
            "fee": p.get("fee", "0"),
            "cost_usd": p.get("cost_usd", "0"),
            "decision_id": p.get("decision_id", ""),
            "ts": fill.event_time,
            "realized_pnl": realized_str,
        })

    return {"date": str(target), "trades": trades}
