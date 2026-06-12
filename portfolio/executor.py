"""
Paper execution adapter.

Simulates market fills with configurable slippage and fees.

PAPER mode:  auto-fills on decision.approved.
ASSISTED mode: parks approved decisions; waits for explicit execute(id) call
               from the operator via the API (Decision Queue).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.decision import Fill, Side
from core.schemas.events import AutonomyMode, EventEnvelope, EventType
from portfolio.ledger import Portfolio

from .settings import PortfolioSettings

logger = structlog.get_logger(__name__)


class HaltedError(RuntimeError):
    """Raised when execution is attempted below ASSISTED authority (e.g. after a halt)."""


class PaperExecutor:
    def __init__(
        self,
        bus: Bus,
        portfolio: Portfolio,
        initial_mode: AutonomyMode = AutonomyMode.OBSERVE,
        settings: PortfolioSettings | None = None,
    ) -> None:
        self._bus = bus
        self._portfolio = portfolio
        self._mode = initial_mode
        self._settings = settings or PortfolioSettings()
        self._approved_sub: Subscription | None = None
        self._stop_sub: Subscription | None = None
        self._mode_sub: Subscription | None = None
        self._halt_sub: Subscription | None = None

        # ASSISTED mode: approved decisions pending human execution
        self._pending: dict[str, dict] = {}

    async def start(self) -> None:
        self._approved_sub = await self._bus.subscribe(
            EventType.DECISION_APPROVED, self._handle_approved
        )
        self._stop_sub = await self._bus.subscribe(
            EventType.RISK_LIMIT_BREACHED, self._handle_stop
        )
        self._mode_sub = await self._bus.subscribe(
            EventType.SYSTEM_MODE_CHANGED, self._handle_mode_change
        )
        # Subscribe to the kill switch directly so the pending queue is flushed
        # even if the halt's mode-change side effect is missed or reordered.
        self._halt_sub = await self._bus.subscribe(
            EventType.RISK_HALT, self._handle_halt
        )
        logger.info("paper_executor.started", mode=self._mode.value)

    async def stop(self) -> None:
        for sub in (self._approved_sub, self._stop_sub, self._mode_sub, self._halt_sub):
            if sub is not None:
                await self._bus.unsubscribe(sub)
        self._approved_sub = None
        self._stop_sub = None
        self._mode_sub = None
        self._halt_sub = None
        logger.info("paper_executor.stopped")

    # ------------------------------------------------------------------
    # Public API (called by gateway route in ASSISTED mode)
    # ------------------------------------------------------------------

    async def execute(self, decision_id: str) -> bool:
        """Operator approves a pending decision in ASSISTED mode.

        Refuses unless the current mode carries ASSISTED-or-greater authority.
        A halt (or any demotion below ASSISTED) both flips the mode and clears
        the queue, so this guard is the kill switch's last line of defence
        against filling a parked order.
        """
        if self._mode.level < AutonomyMode.ASSISTED.level:
            logger.warning(
                "paper_executor.execute_refused", decision_id=decision_id, mode=self._mode.value
            )
            raise HaltedError(
                f"execution requires ASSISTED authority or higher; mode is {self._mode.value}"
            )
        payload = self._pending.pop(decision_id, None)
        if payload is None:
            return False
        await self._fill(payload, datetime.now(UTC))
        return True

    async def close_position(self, instrument: str, now: datetime | None = None) -> bool:
        """
        Manually close an open position (operator action or stop-loss).
        `now` is the financial clock of the triggering event; operator calls
        (no triggering envelope) default to the wall clock.
        """
        position = self._portfolio.positions.get(instrument)
        if not position:
            return False
        current_price = self._portfolio.current_price(instrument)
        if not current_price:
            return False

        slippage = Decimal(str(self._settings.slippage_pct))
        fill_price = (
            current_price * (1 - slippage)
            if position.side == Side.LONG
            else current_price * (1 + slippage)
        )
        fee = fill_price * position.quantity * Decimal(str(self._settings.fee_pct))

        now = now or datetime.now(UTC)
        await self._bus.publish(EventEnvelope(
            event_type=EventType.ORDER_FILLED,
            source="paper_executor",
            event_time=now,
            ingest_time=datetime.now(UTC),
            payload={
                "instrument": instrument,
                "action": "close",
                "side": position.side.value,
                "fill_price": str(fill_price),
                "quantity": str(position.quantity),
                "cost_usd": "0",
                "fee": str(fee),
                "decision_id": position.decision_id,
                "simulated": True,
            },
        ))
        logger.info("paper_executor.closed", instrument=instrument,
                    fill_price=str(fill_price))
        return True

    @property
    def pending_decisions(self) -> list[dict]:
        return list(self._pending.values())

    # ------------------------------------------------------------------
    # Bus handlers
    # ------------------------------------------------------------------

    async def _handle_mode_change(self, envelope: EventEnvelope) -> None:
        self._mode = AutonomyMode(envelope.payload.get("to_mode", self._mode.value))
        # Any demotion below ASSISTED strips execution authority; parked
        # decisions are no longer actionable, so expire them.
        if self._mode.level < AutonomyMode.ASSISTED.level:
            await self._expire_pending("mode_changed", envelope.event_time)

    async def _handle_halt(self, envelope: EventEnvelope) -> None:
        # Kill switch: drop authority and flush the queue immediately, independent
        # of the mode-change event that the halt also publishes.
        self._mode = AutonomyMode.OBSERVE
        await self._expire_pending(envelope.payload.get("reason", "halt"), envelope.event_time)

    async def _expire_pending(self, reason: str, now: datetime) -> None:
        """Clear all parked decisions, emitting an audited decision.expired each."""
        if not self._pending:
            return
        expired = list(self._pending.items())
        self._pending.clear()
        for decision_id, _payload in expired:
            await self._bus.publish(EventEnvelope(
                event_type=EventType.DECISION_EXPIRED,
                source="paper_executor",
                event_time=now,
                ingest_time=datetime.now(UTC),
                correlation_id=UUID(decision_id) if decision_id else None,
                payload={"decision_id": decision_id, "reason": reason},
            ))
            logger.info("paper_executor.expired", decision_id=decision_id, reason=reason)

    async def _handle_approved(self, envelope: EventEnvelope) -> None:
        if self._mode == AutonomyMode.OBSERVE:
            return
        if self._mode == AutonomyMode.PAPER:
            await self._fill(envelope.payload, envelope.event_time)
        elif self._mode == AutonomyMode.ASSISTED:
            decision_id = str(envelope.payload.get("id", ""))
            if decision_id:
                self._pending[decision_id] = envelope.payload
                logger.info("paper_executor.parked", decision_id=decision_id)

    async def _handle_stop(self, envelope: EventEnvelope) -> None:
        instrument: str = envelope.payload.get("instrument", "")
        if instrument:
            await self.close_position(instrument, now=envelope.event_time)

    # ------------------------------------------------------------------

    async def _fill(self, decision_payload: dict, now: datetime) -> None:
        instrument: str = decision_payload.get("proposal", {}).get("instrument", "")
        side_str: str = decision_payload.get("proposal", {}).get("side", "long")
        size_usd = Decimal(str(decision_payload.get("proposal", {}).get("size_usd", "0")))
        decision_id: str = decision_payload.get("id", "")

        if size_usd <= 0:
            logger.warning("paper_executor.zero_size", decision_id=decision_id)
            return

        current_price = self._portfolio.current_price(instrument)
        if not current_price:
            logger.warning("paper_executor.no_price", instrument=instrument)
            return

        slippage = Decimal(str(self._settings.slippage_pct))
        fill_price = (
            current_price * (1 + slippage)
            if side_str == "long"
            else current_price * (1 - slippage)
        )
        fill_price = fill_price.quantize(Decimal("0.01"))
        quantity = (size_usd / fill_price).quantize(Decimal("0.00000001"))
        fee = size_usd * Decimal(str(self._settings.fee_pct))

        stop_price_str: str | None = None
        risk = decision_payload.get("risk")
        if risk and risk.get("stop_price"):
            stop_price_str = str(risk["stop_price"])

        fill = Fill(
            fill_id=str(uuid4()),
            order_id=str(uuid4()),
            ts=now,
            price=fill_price,
            quantity=quantity,
            fee=fee,
            fee_currency="USD",
        )

        await self._bus.publish(EventEnvelope(
            event_type=EventType.ORDER_FILLED,
            source="paper_executor",
            event_time=now,
            ingest_time=datetime.now(UTC),
            correlation_id=UUID(decision_id) if decision_id else None,
            payload={
                "instrument": instrument,
                "action": "open",
                "side": side_str,
                "fill_price": str(fill_price),
                "quantity": str(quantity),
                "cost_usd": str(size_usd),
                "fee": str(fee),
                "stop_price": stop_price_str,
                "decision_id": decision_id,
                "fill": fill.model_dump(mode="json"),
                "simulated": True,
            },
        ))
        logger.info("paper_executor.filled", instrument=instrument, side=side_str,
                    fill_price=str(fill_price), size_usd=str(size_usd))
