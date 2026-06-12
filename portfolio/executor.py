"""
Paper execution adapter.

Simulates market fills with configurable slippage and fees.

PAPER mode:  auto-fills on decision.approved.
ASSISTED mode: parks approved decisions; waits for explicit execute(id) call
               from the operator via the API (Decision Queue).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.decision import Fill, HumanAction, HumanActionType, Side
from core.schemas.events import AutonomyMode, EventEnvelope, EventType
from portfolio.ledger import Portfolio

from .settings import PortfolioSettings

logger = structlog.get_logger(__name__)

# Re-validates a parked decision against current state at execution time.
# Returns (approved, refreshed_payload, rejection_reasons). Structurally the
# RiskEngine.evaluate signature — injected (not imported) to keep portfolio
# free of a dependency on risk/.
PretradeValidator = Callable[[dict[str, Any], datetime], tuple[bool, dict[str, Any], list[str]]]


class HaltedError(RuntimeError):
    """Raised when execution is attempted below ASSISTED authority (e.g. after a halt)."""


class StaleDecisionError(RuntimeError):
    """Raised when a parked decision is expired or fails re-validation at execute time."""


@dataclass
class _ParkedDecision:
    """An ASSISTED-mode approval awaiting operator execution.

    `approved_at` is the approval's event clock, used to enforce the TTL on the
    same timeline the rest of the financial logic uses (two-clock rule)."""

    approved_at: datetime
    payload: dict[str, Any]


class PaperExecutor:
    def __init__(
        self,
        bus: Bus,
        portfolio: Portfolio,
        initial_mode: AutonomyMode = AutonomyMode.OBSERVE,
        settings: PortfolioSettings | None = None,
        validator: PretradeValidator | None = None,
    ) -> None:
        self._bus = bus
        self._portfolio = portfolio
        self._mode = initial_mode
        self._settings = settings or PortfolioSettings()
        # Re-runs pre-trade checks + recomputes size/stop when a parked decision
        # is executed. When None, execute() fills the parked payload as-is.
        self._validator = validator
        self._approved_sub: Subscription | None = None
        self._stop_sub: Subscription | None = None
        self._mode_sub: Subscription | None = None
        self._halt_sub: Subscription | None = None
        self._tick_sub: Subscription | None = None

        # ASSISTED mode: approved decisions pending human execution
        self._pending: dict[str, _ParkedDecision] = {}

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
        # Ticks drive the TTL sweep on the event clock (no wall-clock timer), so
        # parked decisions expire deterministically in live and in replay.
        self._tick_sub = await self._bus.subscribe(
            EventType.MARKET_TICK, self._handle_tick
        )
        logger.info("paper_executor.started", mode=self._mode.value)

    async def stop(self) -> None:
        # Don't silently drop parked decisions on shutdown/restart — expire them
        # with an audited event so the queue is never lost without a trace.
        await self._expire_pending("shutdown", datetime.now(UTC))
        for sub in (self._approved_sub, self._stop_sub, self._mode_sub,
                    self._halt_sub, self._tick_sub):
            if sub is not None:
                await self._bus.unsubscribe(sub)
        self._approved_sub = None
        self._stop_sub = None
        self._mode_sub = None
        self._halt_sub = None
        self._tick_sub = None
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
        parked = self._pending.pop(decision_id, None)
        if parked is None:
            return False

        now = datetime.now(UTC)

        # TTL: a parked approval that has aged out is stale — its checks and stop
        # no longer reflect the market. Expire it instead of filling.
        if self._is_expired(parked, now):
            await self._emit_expired(decision_id, "ttl_expired", now)
            raise StaleDecisionError(f"decision {decision_id} expired before execution")

        # Re-run all pre-trade checks against current state and recompute the
        # size/stop from the current price. A decision approved hours ago must
        # not fill on stale assumptions (position now held, daily loss tripped,
        # price moved through the old stop, …).
        payload = parked.payload
        if self._validator is not None:
            approved, refreshed, reasons = self._validator(payload, now)
            if not approved:
                await self._emit_expired(decision_id, f"revalidation_failed: {reasons}", now)
                raise StaleDecisionError(
                    f"decision {decision_id} failed re-validation: {reasons}"
                )
            payload = refreshed

        await self._fill(payload, now)
        return True

    async def reject(
        self, decision_id: str, reason: str, actor: str = "operator"
    ) -> bool:
        """Operator rejects a parked decision in ASSISTED mode.

        Emits an audited ``decision.rejected`` carrying the operator's
        ``HumanAction`` (Planning §2.10, §7.2 — rejections-with-reasons are
        training signal). The decision_store tracker subscribes to this event,
        so the decision transitions to ``rejected`` status. Returns False if the
        decision isn't in the pending queue (404 at the route).
        """
        parked = self._pending.pop(decision_id, None)
        if parked is None:
            return False

        now = datetime.now(UTC)
        human = HumanAction(
            actor=actor,
            action=HumanActionType.REJECTED,
            note=reason or None,
            ts=now,
        )
        rejected_payload = dict(parked.payload)
        rejected_payload["status"] = "rejected"
        rejected_payload["human"] = human.model_dump(mode="json")

        await self._bus.publish(EventEnvelope(
            event_type=EventType.DECISION_REJECTED,
            source="operator",
            event_time=now,
            ingest_time=now,
            correlation_id=UUID(decision_id) if decision_id else None,
            payload=rejected_payload,
        ))
        logger.info("paper_executor.operator_rejected",
                    decision_id=decision_id, reason=reason)
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
    def pending_decisions(self) -> list[dict[str, Any]]:
        return [parked.payload for parked in self._pending.values()]

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

    async def _handle_tick(self, envelope: EventEnvelope) -> None:
        # Drive the TTL sweep on the event clock so parked decisions expire even
        # when the operator never returns to act on them.
        if self._pending:
            await self._sweep_expired(envelope.event_time)

    def _is_expired(self, parked: _ParkedDecision, now: datetime) -> bool:
        ttl = timedelta(seconds=self._settings.pending_ttl_seconds)
        return now - parked.approved_at >= ttl

    async def _sweep_expired(self, now: datetime) -> None:
        """Expire every parked decision whose TTL has elapsed as of `now`."""
        stale = [did for did, parked in self._pending.items() if self._is_expired(parked, now)]
        for decision_id in stale:
            self._pending.pop(decision_id, None)
            await self._emit_expired(decision_id, "ttl_expired", now)

    async def _expire_pending(self, reason: str, now: datetime) -> None:
        """Clear all parked decisions, emitting an audited decision.expired each."""
        if not self._pending:
            return
        decision_ids = list(self._pending.keys())
        self._pending.clear()
        for decision_id in decision_ids:
            await self._emit_expired(decision_id, reason, now)

    async def _emit_expired(self, decision_id: str, reason: str, now: datetime) -> None:
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
                self._pending[decision_id] = _ParkedDecision(
                    approved_at=envelope.event_time, payload=envelope.payload
                )
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
