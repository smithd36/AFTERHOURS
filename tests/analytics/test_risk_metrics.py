"""Return-series risk/return metrics over the equity curve."""

from __future__ import annotations

import math
from decimal import Decimal

from analytics import (
    daily_returns,
    equity_drawdown,
    historical_var,
    sharpe,
    sortino,
    volatility,
)
from analytics.metrics import PERIODS_PER_YEAR


def _E(*xs: float) -> list[Decimal]:
    return [Decimal(str(x)) for x in xs]


def test_daily_returns_simple() -> None:
    # 100 → 110 → 99 : +10%, -10%
    assert daily_returns(_E(100, 110, 99)) == [0.1, -0.1]


def test_daily_returns_non_positive_prior_is_zero() -> None:
    # a wiped-out book (0 equity) must not divide-by-zero
    assert daily_returns(_E(0, 50)) == [0.0]


def test_daily_returns_too_short() -> None:
    assert daily_returns(_E(100)) == []


def test_sharpe_known_series() -> None:
    returns = [0.01, -0.01, 0.01, -0.01]
    # mean is 0 → Sharpe is 0 (mean/std * sqrt) — defined, not None
    assert sharpe(returns) == 0.0
    # a positive-drift series is positive and annualizes with sqrt(365)
    drift = [0.02, 0.01, 0.02, 0.01]
    m = sum(drift) / len(drift)
    std = math.sqrt(sum((x - m) ** 2 for x in drift) / (len(drift) - 1))
    assert sharpe(drift) == (m / std) * math.sqrt(PERIODS_PER_YEAR)


def test_sharpe_undefined_cases() -> None:
    assert sharpe([0.01]) is None  # <2 points
    assert sharpe([0.01, 0.01, 0.01]) is None  # zero dispersion → undefined


def test_sortino_only_penalizes_downside() -> None:
    returns = [0.05, -0.02, 0.03, -0.01]
    downside = math.sqrt((0.02**2 + 0.01**2) / len(returns))
    mean = sum(returns) / len(returns)
    assert sortino(returns) == (mean / downside) * math.sqrt(PERIODS_PER_YEAR)
    # no losing periods → downside dispersion 0 → undefined
    assert sortino([0.01, 0.02, 0.03]) is None


def test_volatility_annualizes() -> None:
    returns = [0.01, -0.01, 0.02, -0.02]
    mean = sum(returns) / len(returns)
    std = math.sqrt(sum((x - mean) ** 2 for x in returns) / (len(returns) - 1))
    assert volatility(returns) == std * math.sqrt(PERIODS_PER_YEAR)
    assert volatility([0.01]) is None


def test_historical_var_is_positive_loss_fraction() -> None:
    # worst 5% tail of a 20-point series is the single worst return
    returns = [0.01] * 19 + [-0.08]
    assert historical_var(returns, 0.95) == 0.08
    # an all-gains series has no loss at the tail → 0
    assert historical_var([0.01, 0.02, 0.03], 0.95) == 0.0
    assert historical_var([], 0.95) is None


def test_equity_drawdown_value_and_pct_at_same_trough() -> None:
    # peak 150, trough 90 → dd 60, pct 60/150 = 0.4
    dd = equity_drawdown(_E(100, 150, 120, 90, 130))
    assert dd["max_drawdown_value"] == Decimal("60")
    assert dd["max_drawdown_pct"] == 0.4


def test_equity_drawdown_monotonic_up_is_zero() -> None:
    dd = equity_drawdown(_E(100, 110, 120))
    assert dd["max_drawdown_value"] == Decimal("0")
    assert dd["max_drawdown_pct"] == 0.0
