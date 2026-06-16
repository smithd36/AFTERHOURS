"""realized_pnl — the single net-of-fee round-trip formula shared by the
/trades projection and the ledger's close economics."""

from __future__ import annotations

from decimal import Decimal

from analytics import realized_pnl
from core.schemas.decision import Side


def _D(x: float) -> Decimal:
    return Decimal(str(x))


def test_long_profit_net_of_both_fees() -> None:
    # (110 - 100) * 2 = 20 gross, minus 1 entry + 1 exit fee = 18
    pnl = realized_pnl(Side.LONG, _D(100), _D(110), _D(2), _D(1), _D(1))
    assert pnl == Decimal("18")


def test_short_profit_is_price_drop() -> None:
    # short: (entry - exit) * qty = (100 - 90) * 2 = 20, minus 2 fees = 18
    pnl = realized_pnl(Side.SHORT, _D(100), _D(90), _D(2), _D(1), _D(1))
    assert pnl == Decimal("18")


def test_breakeven_price_still_loses_the_fees() -> None:
    pnl = realized_pnl(Side.LONG, _D(100), _D(100), _D(3), _D(2), _D(2))
    assert pnl == Decimal("-4")


def test_matches_ledger_short_loss() -> None:
    # short that moves against us: (100 - 120) * 1 = -20, minus fees
    pnl = realized_pnl(Side.SHORT, _D(100), _D(120), _D(1), _D(0.5), _D(0.5))
    assert pnl == Decimal("-21")
