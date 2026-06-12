from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.schemas.decision import Side


@dataclass
class Position:
    instrument: str
    side: Side
    entry_price: Decimal
    quantity: Decimal          # units of base asset
    current_price: Decimal
    stop_price: Decimal | None = None
    entry_fee: Decimal = Decimal("0")   # fee paid on open; booked into realized P&L at close
    decision_id: str = ""

    @property
    def size_usd(self) -> Decimal:
        return self.entry_price * self.quantity

    @property
    def unrealized_pnl(self) -> Decimal:
        if self.side == Side.LONG:
            return (self.current_price - self.entry_price) * self.quantity
        return (self.entry_price - self.current_price) * self.quantity

    @property
    def equity_contribution(self) -> Decimal:
        """This position's contribution to account equity: posted margin (the
        cost basis, ``size_usd``) plus unrealized P&L.

        For a long this equals raw market value (``current_price × quantity``);
        for a short it correctly *decreases* as the price rises (a loss), unlike
        sign-blind market value. Under the current full-margin model this is
        ``size_usd + unrealized_pnl`` (= ``2·entry·qty − current·qty`` for a short).
        """
        return self.size_usd + self.unrealized_pnl
