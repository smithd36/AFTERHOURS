"""
Risk/return measurement over closed-trade and (step 2) return series.

These are pure, stateless functions: the read-side "economic" half of the
two-gate split (the other half, confidence calibration, lives in
``calibration/``). The economic gate and the portfolio panel both consume
``economic_metrics``; neither owns it, so it lives here rather than in
``calibration/gates.py`` (ADR-011).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

# Daily marks span 24/7 crypto + equities (see analytics/equity_curve.py), so the
# return series is calendar-daily and annualizes with 365, not 252 trading days.
PERIODS_PER_YEAR = 365


def economic_metrics(realized: Sequence[Decimal]) -> dict[str, Any]:
    """Round-trip economics from net-of-fee realized P&L per closed trade.

    `realized` is the Portfolio's per-close P&L (entry + exit fees already
    deducted — see ``Portfolio.close_position``), so every figure here is
    cost-adjusted. ``profit_factor`` is ``None`` when there are no losing trades
    (undefined / effectively infinite); the gate treats that as passing when the
    book is net-positive.
    """
    n = len(realized)
    if n == 0:
        return {
            "trades": 0,
            "net_pnl": Decimal("0"),
            "expectancy": None,
            "win_rate": None,
            "profit_factor": None,
            "max_drawdown": Decimal("0"),
        }
    wins = [r for r in realized if r > 0]
    gross_win = sum(wins, Decimal("0"))
    gross_loss = -sum((r for r in realized if r < 0), Decimal("0"))  # positive magnitude
    net = sum(realized, Decimal("0"))
    # Max peak-to-trough on the cumulative realized-P&L curve.
    peak = cum = max_dd = Decimal("0")
    for r in realized:
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return {
        "trades": n,
        "net_pnl": net,
        "expectancy": net / n,
        "win_rate": len(wins) / n,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "max_drawdown": max_dd,
    }


# ---------------------------------------------------------------------------
# Return-series risk/return metrics (over the equity curve)
#
# These take primitives — equity values (Decimal) or period returns (float) —
# so the module stays decoupled from EquityPoint. Money is Decimal; ratios are
# inherently float. All return None when the series is too short to be defined
# (a single point yields no return; zero dispersion makes a ratio undefined).
# ---------------------------------------------------------------------------


def daily_returns(equity: Sequence[Decimal]) -> list[float]:
    """Per-period simple returns from an equity series. A non-positive prior
    equity yields a 0 return for that step (undefined division, not a crash)."""
    out: list[float] = []
    for prev, cur in zip(equity, equity[1:], strict=False):
        p = float(prev)
        out.append((float(cur) - p) / p if p > 0 else 0.0)
    return out


def _stdev(xs: Sequence[float], mean: float) -> float:
    # Sample standard deviation (n−1); caller guarantees len >= 2.
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))


def sharpe(
    returns: Sequence[float], periods_per_year: int = PERIODS_PER_YEAR
) -> float | None:
    """Annualized Sharpe ratio (risk-free assumed 0). NOTE: on the paper book
    this is net-of-fees but *not* net-of-slippage — see ADR-011."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    std = _stdev(returns, mean)
    if std == 0:
        return None
    return (mean / std) * math.sqrt(periods_per_year)


def sortino(
    returns: Sequence[float], periods_per_year: int = PERIODS_PER_YEAR
) -> float | None:
    """Annualized Sortino ratio — like Sharpe but penalizing only downside
    dispersion (returns below 0)."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    downside = math.sqrt(sum(min(0.0, r) ** 2 for r in returns) / len(returns))
    if downside == 0:
        return None
    return (mean / downside) * math.sqrt(periods_per_year)


def volatility(
    returns: Sequence[float], periods_per_year: int = PERIODS_PER_YEAR
) -> float | None:
    """Annualized standard deviation of returns."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    return _stdev(returns, mean) * math.sqrt(periods_per_year)


def historical_var(returns: Sequence[float], level: float = 0.95) -> float | None:
    """Historical one-period Value-at-Risk at ``level`` confidence, as a positive
    loss fraction (0 when the relevant tail quantile is non-negative)."""
    if not returns:
        return None
    ordered = sorted(returns)  # worst first
    # The tail holds ~(1−level)·n observations; VaR is its least-bad member
    # (the threshold). `round` absorbs the float error in (1−level)·n — e.g.
    # 0.05·20 evaluates to 1.0000000000000009, which must be 1, not 2 — and the
    # floor of 1 keeps the single worst observation as the tail for small n.
    tail = max(1, round((1 - level) * len(ordered)))
    q = ordered[tail - 1]
    return -q if q < 0 else 0.0


def equity_drawdown(equity: Sequence[Decimal]) -> dict[str, Any]:
    """Worst peak-to-trough on the mark-to-market equity curve. Reports the
    dollar value and the percentage *at that same trough* (unlike the
    realized-trade ``max_drawdown`` in ``economic_metrics``, this includes
    unrealized P&L and has a time axis)."""
    if not equity:
        return {"max_drawdown_value": Decimal("0"), "max_drawdown_pct": 0.0}
    peak = equity[0]
    max_dd_value = Decimal("0")
    max_dd_pct = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd_value:
            max_dd_value = dd
            max_dd_pct = float(dd / peak) if peak > 0 else 0.0
    return {"max_drawdown_value": max_dd_value, "max_drawdown_pct": max_dd_pct}
