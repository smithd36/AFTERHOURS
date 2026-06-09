from __future__ import annotations

from dataclasses import dataclass, field
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
    decision_id: str = ""

    @property
    def size_usd(self) -> Decimal:
        return self.entry_price * self.quantity

    @property
    def current_value(self) -> Decimal:
        return self.current_price * self.quantity

    @property
    def unrealized_pnl(self) -> Decimal:
        if self.side == Side.LONG:
            return (self.current_price - self.entry_price) * self.quantity
        return (self.entry_price - self.current_price) * self.quantity
