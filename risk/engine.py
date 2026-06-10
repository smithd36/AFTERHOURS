"""
Risk engine — the deterministic gatekeeper.

Every decision passes through here before any capital is committed.
The LLM cannot bypass this (PLANNING §2.4, §4.5).

Responsibilities:
  - Pre-trade checks (mode, halt, limits, exposure)
  - Deterministic sizing via sizing.py
  - Stop price computation
  - Stop-loss monitoring: watches live ticks and closes positions that breach stops
  - Kill switch: halts via SYSTEM_MODE_CHANGED → OBSERVE
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.decision import RiskAssessment, RiskVerdict, Side
from core.schemas.events import AutonomyMode, EventEnvelope, EventType
from portfolio.ledger import Portfolio

from .settings import RiskSettings
from .sizing import deterministic_size

logger = structlog.get_logger(__name__)


class RiskEngine:
    def __init__(
        self,
        bus: Bus,
        portfolio: Portfolio,
        initial_mode: AutonomyMode = AutonomyMode.OBSERVE,
        settings: RiskSettings | None = None,
    ) -> None:
        self._bus = bus
        self._portfolio = portfolio
        self._mode = initial_mode
        self._settings = settings or RiskSettings()
        self._proposed_sub: Subscription | None = None
        self._tick_sub: Subscription | None = None
        self._mode_sub: Subscription | None = None

    async def start(self) -> None:
        self._proposed_sub = await self._bus.subscribe(
            EventType.DECISION_PROPOSED, self._handle_proposed
        )
        self._tick_sub = await self._bus.subscribe(
            EventType.MARKET_TICK, self._handle_tick
        )
        self._mode_sub = await self._bus.subscribe(
            EventType.SYSTEM_MODE_CHANGED, self._handle_mode_change
        )
        logger.info("risk_engine.started", mode=self._mode.value)

    async def stop(self) -> None:
        for sub in (self._proposed_sub, self._tick_sub, self._mode_sub):
            if sub is not None:
                await self._bus.unsubscribe(sub)
        self._proposed_sub = None
        self._tick_sub = None
        self._mode_sub = None
        logger.info("risk_engine.stopped")

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------

    async def _handle_mode_change(self, envelope: EventEnvelope) -> None:
        new_mode = AutonomyMode(envelope.payload.get("to_mode", self._mode.value))
        logger.info("risk_engine.mode_changed", from_mode=self._mode.value, to_mode=new_mode.value)
        self._mode = new_mode

    # ------------------------------------------------------------------
    # Pre-trade checks
    # ------------------------------------------------------------------

    async def _handle_proposed(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        decision_id: str = str(payload.get("id", ""))
        instrument: str = str(payload.get("proposal", {}).get("instrument", ""))
        # Verdict events inherit the proposal's event clock so the decision
        # lifecycle stays on one timeline in live and in backtest replay.
        now = envelope.event_time

        # Observe mode: shadow decision, no execution
        if self._mode == AutonomyMode.OBSERVE:
            await self._reject(decision_id, instrument, now, payload,
                               ["observe_mode: shadow decision logged for calibration"])
            return

        portfolio_value = self._portfolio.total_value

        # Max open positions
        if self._portfolio.open_position_count >= self._settings.max_open_positions:
            await self._reject(decision_id, instrument, now, payload,
                               [f"max_open_positions: {self._settings.max_open_positions} already open"])
            return

        # No pyramiding: reject if we already hold this instrument
        if instrument in self._portfolio.positions:
            await self._reject(decision_id, instrument, now, payload,
                               [f"position_exists: already holding {instrument}"])
            return

        # Daily loss circuit breaker
        if portfolio_value > 0:
            daily_loss_pct = float(-self._portfolio.daily_realized_pnl / portfolio_value)
            if daily_loss_pct >= self._settings.max_daily_loss_pct:
                await self._reject(decision_id, instrument, now, payload,
                                   [f"daily_loss_limit: {daily_loss_pct:.1%} >= "
                                    f"{self._settings.max_daily_loss_pct:.1%}"])
                return

        # Deterministic sizing
        size_usd = deterministic_size(
            portfolio_value=portfolio_value,
            max_trade_loss_pct=self._settings.max_trade_loss_pct,
            stop_loss_pct=self._settings.stop_loss_pct,
            max_position_pct=self._settings.max_position_pct,
        )

        if size_usd <= 0:
            await self._reject(decision_id, instrument, now, payload,
                               ["insufficient_capital: portfolio too small to size a position"])
            return

        # Stop price
        side_str: str = payload.get("proposal", {}).get("side", "long")
        current_price = self._portfolio.current_price(instrument)
        stop_price: Decimal | None = None
        if current_price:
            offset = current_price * Decimal(str(self._settings.stop_loss_pct))
            stop_price = (current_price - offset if side_str == "long" else current_price + offset)
            stop_price = stop_price.quantize(Decimal("0.01"))

        risk = RiskAssessment(
            max_loss_pct=self._settings.max_trade_loss_pct,
            stop_price=stop_price,
            invalidation_conditions=[],
            risk_engine_verdict=RiskVerdict.APPROVED,
        )

        approved_payload = dict(payload)
        approved_payload["proposal"] = {
            **payload.get("proposal", {}),
            "size_usd": str(size_usd),
        }
        approved_payload["risk"] = risk.model_dump(mode="json")
        approved_payload["status"] = "approved"

        await self._bus.publish(EventEnvelope(
            event_type=EventType.DECISION_APPROVED,
            source="risk_engine",
            event_time=now,
            ingest_time=datetime.now(UTC),
            correlation_id=UUID(decision_id) if decision_id else None,
            payload=approved_payload,
        ))
        logger.info("risk_engine.approved", decision_id=decision_id,
                    instrument=instrument, size_usd=str(size_usd))

    async def _reject(
        self,
        decision_id: str,
        instrument: str,
        now: datetime,
        payload: dict,
        reasons: list[str],
    ) -> None:
        from core.schemas.decision import RiskVerdict
        rejected_payload = dict(payload)
        rejected_payload["status"] = "rejected"
        rejected_payload["risk"] = RiskAssessment(
            max_loss_pct=0.0,
            invalidation_conditions=[],
            risk_engine_verdict=RiskVerdict.REJECTED,
            rejection_reasons=reasons,
        ).model_dump(mode="json")

        await self._bus.publish(EventEnvelope(
            event_type=EventType.DECISION_REJECTED,
            source="risk_engine",
            event_time=now,
            ingest_time=datetime.now(UTC),
            correlation_id=UUID(decision_id) if decision_id else None,
            payload=rejected_payload,
        ))
        logger.info("risk_engine.rejected", decision_id=decision_id,
                    instrument=instrument, reasons=reasons)

    # ------------------------------------------------------------------
    # Stop-loss monitoring
    # ------------------------------------------------------------------

    async def _handle_tick(self, envelope: EventEnvelope) -> None:
        p = envelope.payload
        instrument: str = p.get("instrument", "")
        price_str: str = p.get("price", "")
        if not instrument or not price_str:
            return

        position = self._portfolio.positions.get(instrument)
        if not position or not position.stop_price:
            return

        price = Decimal(price_str)
        breached = (
            (position.side == Side.LONG and price <= position.stop_price) or
            (position.side == Side.SHORT and price >= position.stop_price)
        )
        if not breached:
            return

        now = envelope.event_time  # the breaching tick's clock — replay-safe
        logger.warning("risk_engine.stop_breached", instrument=instrument,
                       price=str(price), stop=str(position.stop_price))

        await self._bus.publish(EventEnvelope(
            event_type=EventType.RISK_LIMIT_BREACHED,
            source="risk_engine",
            event_time=now,
            ingest_time=datetime.now(UTC),
            payload={
                "instrument": instrument,
                "reason": "stop_loss",
                "trigger_price": str(price),
                "stop_price": str(position.stop_price),
                "decision_id": position.decision_id,
            },
        ))
