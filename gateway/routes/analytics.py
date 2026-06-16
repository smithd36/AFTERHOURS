"""Risk/return analytics over the mark-to-market equity curve.

Read-side projection (ADR-011): replays persisted fills + ticks on demand, so
there is no analytics state on app.state — just the event store and the paper
book for the realized-trade series.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request

from analytics import (
    build_equity_curve,
    daily_returns,
    economic_metrics,
    equity_drawdown,
    historical_var,
    sharpe,
    sortino,
    volatility,
)
from core.schemas.events import EventType

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _round(x: float | None, places: int = 4) -> float | None:
    return None if x is None else round(x, places)


@router.get("")
async def get_analytics(request: Request) -> dict[str, Any]:
    """Equity curve + Sharpe/Sortino/volatility/VaR and equity-curve drawdown.

    Sharpe here is net-of-fees but not net-of-slippage (paper book) — the panel
    surfaces it informationally; it is *not* a promotion-gate criterion (ADR-011).
    """
    store = request.app.state.event_store
    portfolio = request.app.state.portfolio

    fills = await store.range([EventType.ORDER_FILLED.value])
    realized = economic_metrics(portfolio.realized_trades)

    if not fills:
        return {
            "equity_curve": [],
            "metrics": {
                "sharpe": None,
                "sortino": None,
                "volatility": None,
                "var_95": None,
                "max_drawdown_value": str(realized["max_drawdown"]),
                "max_drawdown_pct": 0.0,
                "net_pnl": str(realized["net_pnl"]),
                "trades": realized["trades"],
            },
            "n_days": 0,
        }

    # Only ticks from the first fill onward can affect a mark.
    start = fills[0].event_time
    ticks = await store.range([EventType.MARKET_TICK.value], start=start)

    today = datetime.now(UTC).date()
    points = await build_equity_curve(fills, ticks, today=today)
    equity = [p.equity for p in points]
    returns = daily_returns(equity)
    dd = equity_drawdown(equity)

    return {
        "equity_curve": [
            {"day": p.day.isoformat(), "equity": str(p.equity)} for p in points
        ],
        "metrics": {
            "sharpe": _round(sharpe(returns), 3),
            "sortino": _round(sortino(returns), 3),
            "volatility": _round(volatility(returns), 4),
            "var_95": _round(historical_var(returns, 0.95), 4),
            "max_drawdown_value": str(dd["max_drawdown_value"]),
            "max_drawdown_pct": _round(dd["max_drawdown_pct"], 4),
            "net_pnl": str(realized["net_pnl"]),
            "trades": realized["trades"],
        },
        "n_days": len(points),
    }
