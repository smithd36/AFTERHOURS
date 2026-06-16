"""economic_metrics — cost-adjusted round-trip economics (moved from test_gates)."""

from __future__ import annotations

from decimal import Decimal

from analytics import economic_metrics


def _D(*xs: float) -> list[Decimal]:
    return [Decimal(str(x)) for x in xs]


def test_economic_metrics_math() -> None:
    """Expectancy, profit factor and drawdown over a known net-of-fee series."""
    m = economic_metrics(_D(100, -50, 100, -30))
    assert m["trades"] == 4
    assert m["net_pnl"] == Decimal("120")
    assert m["expectancy"] == Decimal("30")  # 120 / 4
    assert m["win_rate"] == 0.5
    assert m["profit_factor"] == Decimal("2.5")  # 200 gross win / 80 gross loss
    # equity curve 100, 50, 150, 120 → worst peak-to-trough is 150→100 = 50
    assert m["max_drawdown"] == Decimal("50")


def test_economic_metrics_no_losses_has_undefined_profit_factor() -> None:
    m = economic_metrics(_D(40, 60))
    assert m["profit_factor"] is None  # no losing trade → undefined (treated as inf)
    assert m["max_drawdown"] == Decimal("0")


def test_economic_metrics_empty() -> None:
    m = economic_metrics([])
    assert m["trades"] == 0
    assert m["expectancy"] is None
