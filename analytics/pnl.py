"""
Realized P&L arithmetic — the single definition of a closed round-trip's
net-of-fee profit.

Mirrors ``Portfolio.close_position``'s economics exactly (long:
``(exit − entry)·qty``; short: ``(entry − exit)·qty``; both legs' fees
subtracted). Extracted so the portfolio ``/trades`` projection and (step 2) the
equity-curve builder share one formula instead of drifting copies (ADR-011).
"""

from __future__ import annotations

from decimal import Decimal

from core.schemas.decision import Side


def realized_pnl(
    side: Side,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
    entry_fee: Decimal,
    exit_fee: Decimal,
) -> Decimal:
    """Net-of-fee realized P&L for one closed round-trip."""
    gross = (exit_price - entry_price) * quantity
    if side == Side.SHORT:
        gross = -gross
    return gross - entry_fee - exit_fee
