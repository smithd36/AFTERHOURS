"""
Outcome resolver — scores every decision against subsequent price action.

Subscribes to decision.proposed and tracks each decision until its time
horizon elapses (or its stop is breached, or its originating thesis is
invalidated), then emits decision.resolved with the realized result.
Shadow decisions (OBSERVE-mode rejections) are resolved too — they form
the Observe → Paper calibration sample (PLANNING Appendix B).

Everything is driven by tick `event_time`, never the wall clock, so the
same component behaves identically in live operation and backtest replay
(two-clock rule, PLANNING §4.6). The entry price is the first tick at or
after the proposal; if no tick arrives within the horizon window the
decision is dropped as unscoreable rather than scored against stale data.

Known limitation: a decision whose horizon fully elapses while the app is
down is only caught up as far as the tick history replayed at startup
(see `replay()` and the gateway lifespan); beyond that it is dropped.
The backtest engine is the full-recovery path.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.decision import Side, TimeHorizon
from core.schemas.events import AutonomyMode, EventEnvelope, EventType

from .settings import CalibrationSettings

logger = structlog.get_logger(__name__)


@dataclass
class _Pending:
    decision_id: str
    instrument: str
    side: Side
    confidence: float
    mode_at_proposal: AutonomyMode
    proposed_at: datetime
    deadline: datetime
    thesis_id: str | None
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None


class OutcomeResolver:
    def __init__(
        self,
        bus: Bus,
        initial_mode: AutonomyMode = AutonomyMode.OBSERVE,
        settings: CalibrationSettings | None = None,
    ) -> None:
        self._bus = bus
        self._mode = initial_mode
        self._settings = settings or CalibrationSettings()
        self._pending: dict[str, _Pending] = {}
        self._last_price: dict[str, Decimal] = {}  # instrument → last tick price
        self._subs: list[Subscription] = []

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def start(self) -> None:
        for pattern, handler in (
            (EventType.DECISION_PROPOSED, self._handle_proposed),
            (EventType.DECISION_APPROVED, self._handle_approved),
            (EventType.MARKET_TICK, self._handle_tick),
            (EventType.THESIS_INVALIDATED, self._handle_thesis_invalidated),
            (EventType.SYSTEM_MODE_CHANGED, self._handle_mode_change),
        ):
            self._subs.append(await self._bus.subscribe(pattern, handler))
        logger.info("outcome_resolver.started", pending=len(self._pending))

    async def stop(self) -> None:
        for sub in self._subs:
            await self._bus.unsubscribe(sub)
        self._subs.clear()
        logger.info("outcome_resolver.stopped")

    # ------------------------------------------------------------------
    # Startup rehydration
    # ------------------------------------------------------------------

    def seed(self, proposals: Iterable[tuple[EventEnvelope, AutonomyMode]]) -> None:
        """
        Re-track unresolved decision.proposed envelopes from the event store.
        The historical autonomy mode cannot be observed directly, so the
        caller supplies it per decision (the gateway derives it from the
        correlated risk-verdict events).
        """
        for envelope, mode in proposals:
            self._add_pending(envelope, mode)

    async def replay(self, envelopes: Iterable[EventEnvelope]) -> None:
        """
        Replay historical tick / thesis-invalidation events (in event_time
        order) to catch up seeded decisions. Resolutions emitted here are
        published to the bus exactly like live ones — same audit trail.
        """
        for envelope in envelopes:
            if envelope.event_type == EventType.MARKET_TICK:
                await self._handle_tick(envelope)
            elif envelope.event_type == EventType.THESIS_INVALIDATED:
                await self._handle_thesis_invalidated(envelope)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_mode_change(self, envelope: EventEnvelope) -> None:
        self._mode = AutonomyMode(envelope.payload.get("to_mode", self._mode.value))

    async def _handle_proposed(self, envelope: EventEnvelope) -> None:
        self._add_pending(envelope, self._mode)

    async def _handle_approved(self, envelope: EventEnvelope) -> None:
        # The risk engine attaches a stop price on approval; a stop breach
        # resolves the decision early (matching what execution would do).
        payload = envelope.payload
        pending = self._pending.get(str(payload.get("id", "")))
        if pending is None:
            return
        stop_raw = (payload.get("risk") or {}).get("stop_price")
        if stop_raw:
            with suppress(InvalidOperation):
                pending.stop_price = Decimal(str(stop_raw))

    async def _handle_tick(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        instrument = str(payload.get("instrument", ""))
        price_raw = payload.get("price", "")
        if not instrument or not price_raw:
            return
        try:
            price = Decimal(str(price_raw))
        except InvalidOperation:
            return
        tick_time = envelope.event_time
        self._last_price[instrument] = price

        to_resolve: list[tuple[_Pending, str]] = []
        to_drop: list[str] = []
        for pending in self._pending.values():
            if pending.instrument != instrument:
                continue
            if pending.entry_price is None:
                if tick_time >= pending.deadline:
                    # No price seen during the whole window — unscoreable.
                    to_drop.append(pending.decision_id)
                elif tick_time >= pending.proposed_at:
                    pending.entry_price = price
                continue
            if tick_time >= pending.deadline:
                to_resolve.append((pending, "horizon_elapsed"))
            elif pending.stop_price is not None and (
                (pending.side is Side.LONG and price <= pending.stop_price)
                or (pending.side is Side.SHORT and price >= pending.stop_price)
            ):
                to_resolve.append((pending, "stop_breached"))

        for decision_id in to_drop:
            self._pending.pop(decision_id, None)
            logger.warning("outcome_resolver.dropped_unscoreable", decision_id=decision_id)
        for pending, reason in to_resolve:
            await self._resolve(pending, price, tick_time, reason)

    async def _handle_thesis_invalidated(self, envelope: EventEnvelope) -> None:
        thesis_id = str(envelope.payload.get("thesis_id", ""))
        if not thesis_id:
            return
        matching = [p for p in self._pending.values() if p.thesis_id == thesis_id]
        for pending in matching:
            price = self._last_price.get(pending.instrument)
            if pending.entry_price is None or price is None:
                self._pending.pop(pending.decision_id, None)
                logger.warning(
                    "outcome_resolver.dropped_unscoreable", decision_id=pending.decision_id
                )
                continue
            await self._resolve(pending, price, envelope.event_time, "thesis_invalidated")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _add_pending(self, envelope: EventEnvelope, mode: AutonomyMode) -> None:
        payload = envelope.payload
        decision_id = str(payload.get("id", ""))
        proposal = payload.get("proposal") or {}
        instrument = str(proposal.get("instrument", ""))
        if not decision_id or not instrument:
            return
        try:
            side = Side(str(proposal.get("side", "")))
        except ValueError:
            return
        try:
            horizon = TimeHorizon(str(proposal.get("time_horizon", "")))
        except ValueError:
            horizon = TimeHorizon.INTRADAY
        proposed_at = envelope.event_time
        thesis_raw = payload.get("originating_thesis_id")
        self._pending[decision_id] = _Pending(
            decision_id=decision_id,
            instrument=instrument,
            side=side,
            confidence=float(payload.get("confidence", 0.0)),
            mode_at_proposal=mode,
            proposed_at=proposed_at,
            deadline=proposed_at + self._horizon_duration(horizon),
            thesis_id=str(thesis_raw) if thesis_raw else None,
        )

    def _horizon_duration(self, horizon: TimeHorizon) -> timedelta:
        s = self._settings
        return {
            TimeHorizon.SCALP: timedelta(minutes=s.horizon_scalp_minutes),
            TimeHorizon.INTRADAY: timedelta(hours=s.horizon_intraday_hours),
            TimeHorizon.SWING: timedelta(days=s.horizon_swing_days),
            TimeHorizon.POSITION: timedelta(days=s.horizon_position_days),
        }[horizon]

    async def _resolve(
        self,
        pending: _Pending,
        resolution_price: Decimal,
        resolved_at: datetime,
        reason: str,
    ) -> None:
        self._pending.pop(pending.decision_id, None)
        entry = pending.entry_price
        if entry is None or entry == 0:
            return
        raw_return = float((resolution_price - entry) / entry)
        direction = 1.0 if pending.side is Side.LONG else -1.0
        # Side-adjusted: > 0 means the predicted direction was profitable.
        realized_return_pct = raw_return * direction * 100
        hit = realized_return_pct > 0

        try:
            correlation_id: UUID | None = UUID(pending.decision_id)
        except ValueError:
            correlation_id = None

        await self._bus.publish(
            EventEnvelope(
                event_type=EventType.DECISION_RESOLVED,
                source="outcome_resolver",
                event_time=resolved_at,  # the resolving tick's clock — replay-safe
                ingest_time=datetime.now(UTC),
                correlation_id=correlation_id,
                payload={
                    "decision_id": pending.decision_id,
                    "instrument": pending.instrument,
                    "predicted_side": pending.side.value,
                    "confidence": pending.confidence,
                    "mode_at_proposal": pending.mode_at_proposal.value,
                    "entry_price": str(entry),
                    "resolution_price": str(resolution_price),
                    "realized_return_pct": realized_return_pct,
                    "hit": hit,
                    "resolution_reason": reason,
                    "proposed_at": pending.proposed_at.isoformat(),
                    "resolved_at": resolved_at.isoformat(),
                },
            )
        )
        logger.info(
            "outcome_resolver.resolved",
            decision_id=pending.decision_id,
            instrument=pending.instrument,
            hit=hit,
            return_pct=round(realized_return_pct, 3),
            reason=reason,
        )
