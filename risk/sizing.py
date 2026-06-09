"""
Deterministic position sizing — fixed-fractional method.

The LLM never contributes to this calculation (PLANNING §4.5).
"""

from __future__ import annotations

from decimal import Decimal


def deterministic_size(
    portfolio_value: Decimal,
    max_trade_loss_pct: float,
    stop_loss_pct: float,
    max_position_pct: float,
) -> Decimal:
    """
    Risk-per-trade / stop-distance, capped at max_position.

    Example: $10k portfolio, 2% risk, 3% stop → $200 / 0.03 = $6,666.
    Capped at 5% of portfolio = $500. Result: $500.
    """
    if portfolio_value <= 0:
        return Decimal("0")

    risk_amount = portfolio_value * Decimal(str(max_trade_loss_pct))
    stop_distance = Decimal(str(stop_loss_pct))
    if stop_distance <= 0:
        return Decimal("0")

    raw_size = risk_amount / stop_distance
    max_size = portfolio_value * Decimal(str(max_position_pct))
    return min(raw_size, max_size).quantize(Decimal("0.01"))
