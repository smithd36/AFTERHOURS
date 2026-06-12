"""
Paper portfolio ledger.

Subscribes to order.filled to open/close positions and to market.tick
to keep unrealized P&L current. All arithmetic in Decimal.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.decision import Side
from core.schemas.events import EventEnvelope, EventType

from .models import Position
from .settings import PortfolioSettings

logger = structlog.get_logger(__name__)


class Portfolio:
    def __init__(self, bus: Bus, settings: PortfolioSettings | None = None) -> None:
        self._bus = bus
        self._settings = settings or PortfolioSettings()
        self._fill_sub: Subscription | None = None
        self._tick_sub: Subscription | None = None

        self.cash: Decimal = self._settings.initial_cash
        self.positions: dict[str, Position] = {}
        self._prices: dict[str, Decimal] = {}

        # Realized P&L for the current UTC trading day. Keyed on event time
        # (not wall clock) so the breaker behaves identically under live trading
        # and backtest replay. `_daily_date` is the UTC day the accumulator
        # belongs to; it rolls over — and the accumulator resets — when a later
        # event crosses into a new day.
        self._daily_pnl: Decimal = Decimal("0")
        self._daily_date: date | None = None

    async def start(self) -> None:
        self._fill_sub = await self._bus.subscribe(EventType.ORDER_FILLED, self._handle_fill)
        self._tick_sub = await self._bus.subscribe(EventType.MARKET_TICK, self._handle_tick)
        logger.info("portfolio.started", initial_cash=str(self.cash))

    async def stop(self) -> None:
        for sub in (self._fill_sub, self._tick_sub):
            if sub is not None:
                await self._bus.unsubscribe(sub)
        self._fill_sub = None
        self._tick_sub = None
        logger.info("portfolio.stopped")

    # ------------------------------------------------------------------
    # Startup rehydration
    # ------------------------------------------------------------------

    async def rehydrate(self, fills: Iterable[EventEnvelope]) -> None:
        """Rebuild cash, open positions and the daily-P&L accumulator by
        replaying persisted ``order.filled`` events in event-time order.

        Without this a restart silently resets the paper book to
        ``initial_cash`` and forgets every open position — corrupting the
        autonomy-gate evidence window (realized P&L / daily-loss state) that
        the Paper → Assisted promotion depends on (PLANNING Appendix B). It
        mirrors :meth:`OutcomeResolver.replay`.

        Pure state reconstruction — publishes nothing. Must be called *before*
        :meth:`start` so a replayed fill is never also applied as a live event.
        The daily accumulator self-corrects across a day boundary: the
        ``daily_realized_pnl`` getter is event-time keyed, so a stale prior-day
        total reads as 0 once the clock advances. Open positions carry the
        entry price as ``current_price`` until the first live tick refreshes it.
        """
        count = 0
        for envelope in fills:
            await self._handle_fill(envelope)
            count += 1
        logger.info("portfolio.rehydrated", fills=count, cash=str(self.cash),
                    open_positions=len(self.positions))

    # ------------------------------------------------------------------
    # Queries (used by risk engine and API routes)
    # ------------------------------------------------------------------

    @property
    def total_value(self) -> Decimal:
        # Equity contribution (margin + unrealized P&L), not raw market value, so
        # a losing short reduces equity instead of inflating it (sign-blind
        # market value would rise as a short loses).
        position_value = sum(
            (p.equity_contribution for p in self.positions.values()), Decimal("0")
        )
        return self.cash + position_value

    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    @property
    def unrealized_pnl(self) -> Decimal:
        return sum((p.unrealized_pnl for p in self.positions.values()), Decimal("0"))

    def current_price(self, instrument: str) -> Decimal | None:
        return self._prices.get(instrument)

    def daily_realized_pnl(self, as_of: datetime) -> Decimal:
        """Realized P&L for the UTC day containing `as_of` (event-time keyed).

        Returns 0 once `as_of` has advanced past the day of the last recorded
        close — the prior day's losses no longer count against the daily breaker.
        Callers in financial logic must pass an event clock; display/ops callers
        may pass the wall clock.
        """
        if self._daily_date is None or as_of.astimezone(UTC).date() > self._daily_date:
            return Decimal("0")
        return self._daily_pnl

    def _rollover_if_new_day(self, as_of: datetime) -> None:
        """Advance the daily accumulator to the UTC day of `as_of`, resetting it
        to zero when the day changes."""
        day = as_of.astimezone(UTC).date()
        if self._daily_date is None:
            self._daily_date = day
        elif day > self._daily_date:
            self._daily_date = day
            self._daily_pnl = Decimal("0")

    def snapshot(self) -> dict[str, object]:
        return {
            "cash": str(self.cash),
            "total_value": str(self.total_value),
            "unrealized_pnl": str(self.unrealized_pnl),
            "daily_realized_pnl": str(self.daily_realized_pnl(datetime.now(UTC))),
            "open_positions": len(self.positions),
            "positions": {
                inst: {
                    "side": p.side.value,
                    "entry_price": str(p.entry_price),
                    "current_price": str(p.current_price),
                    "quantity": str(p.quantity),
                    "size_usd": str(p.size_usd),
                    "unrealized_pnl": str(p.unrealized_pnl),
                    "stop_price": str(p.stop_price) if p.stop_price else None,
                    "decision_id": p.decision_id,
                }
                for inst, p in self.positions.items()
            },
        }

    # ------------------------------------------------------------------
    # Mutations (called by executor or via route for manual close)
    # ------------------------------------------------------------------

    def open_position(
        self,
        instrument: str,
        side: Side,
        fill_price: Decimal,
        quantity: Decimal,
        cost_usd: Decimal,
        stop_price: Decimal | None,
        decision_id: str,
    ) -> None:
        self.cash -= cost_usd
        # Defence in depth: the risk engine's affordability gate should keep this
        # from ever happening. If cash still goes negative, a sizing/gate bug has
        # let an unaffordable order through — surface it loudly rather than carry
        # silent leverage on the book.
        if self.cash < 0:
            logger.error("portfolio.cash_negative", instrument=instrument,
                         cash=str(self.cash), cost_usd=str(cost_usd))
        self.positions[instrument] = Position(
            instrument=instrument,
            side=side,
            entry_price=fill_price,
            quantity=quantity,
            current_price=fill_price,
            stop_price=stop_price,
            decision_id=decision_id,
        )
        logger.info("portfolio.position_opened", instrument=instrument, side=side.value,
                    fill_price=str(fill_price), quantity=str(quantity))

    def close_position(
        self, instrument: str, fill_price: Decimal, fee: Decimal, event_time: datetime
    ) -> Decimal:
        """Close an open position. Returns realized P&L (net of fees).

        `event_time` is the venue/source clock of the closing fill; it drives the
        UTC-day rollover of the daily realized-P&L accumulator (two-clock rule).
        """
        position = self.positions.pop(instrument, None)
        if position is None:
            return Decimal("0")

        proceeds = fill_price * position.quantity
        cost_basis = position.entry_price * position.quantity
        if position.side == Side.LONG:
            realized = proceeds - cost_basis - fee
            self.cash += proceeds - fee
        else:
            realized = cost_basis - proceeds - fee
            self.cash += cost_basis + (cost_basis - proceeds) - fee

        self._rollover_if_new_day(event_time)
        self._daily_pnl += realized
        logger.info("portfolio.position_closed", instrument=instrument,
                    realized_pnl=str(realized), fill_price=str(fill_price))
        return realized

    # ------------------------------------------------------------------
    # Bus handlers
    # ------------------------------------------------------------------

    async def _handle_tick(self, envelope: EventEnvelope) -> None:
        p = envelope.payload
        instrument: str = p.get("instrument", "")
        price_str: str = p.get("price", "")
        if not instrument or not price_str:
            return
        price = Decimal(price_str)
        self._prices[instrument] = price
        if instrument in self.positions:
            self.positions[instrument].current_price = price

    async def _handle_fill(self, envelope: EventEnvelope) -> None:
        p = envelope.payload
        instrument: str = p.get("instrument", "")
        action: str = p.get("action", "open")   # "open" | "close"
        side_str: str = p.get("side", "long")
        fill_price = Decimal(str(p.get("fill_price", "0")))
        quantity = Decimal(str(p.get("quantity", "0")))
        cost_usd = Decimal(str(p.get("cost_usd", "0")))
        fee = Decimal(str(p.get("fee", "0")))
        stop_price_str: str | None = p.get("stop_price")
        stop_price = Decimal(stop_price_str) if stop_price_str else None
        decision_id: str = p.get("decision_id", "")

        if action == "open":
            self.open_position(
                instrument=instrument,
                side=Side(side_str),
                fill_price=fill_price,
                quantity=quantity,
                cost_usd=cost_usd + fee,
                stop_price=stop_price,
                decision_id=decision_id,
            )
        elif action == "close":
            self.close_position(instrument, fill_price, fee, envelope.event_time)
