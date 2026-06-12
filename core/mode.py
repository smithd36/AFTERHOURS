"""
Single source of truth for the autonomy mode.

The mode used to be cached independently in four places — the gateway app
state, the risk engine, the paper executor and the outcome resolver — each
re-synced by separately handling ``system.mode_changed``. A dropped or
reordered event left two subsystems trading in different modes: benign in
paper, real money once the live executor lands in Phase 6.

``ModeController`` owns the value. Every component holds a reference and reads
``current`` at the point of use instead of caching its own copy, so there is
nothing to fall out of sync. The value changes in exactly one place —
``set()`` / ``halt()`` — which updates it *before* publishing the audit event,
so any subscriber that reads ``current`` during fan-out already sees the new
mode. The published events remain the audit trail and still drive reactive
side effects (e.g. the executor flushing parked decisions on demotion); they
are no longer the mechanism by which anyone learns the current mode.

Restart fail-safe (ADR-004, PLANNING §5): the mode is deliberately *not*
persisted. Every process starts in OBSERVE and stays read-only until the
operator explicitly promotes it, so a crash or redeploy can never silently
resume live trading.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from core.bus.base import Bus
from core.schemas.events import AutonomyMode, EventEnvelope, EventType

logger = structlog.get_logger(__name__)


class InvalidModeTransition(ValueError):
    """Raised by ``set()`` for a transition the autonomy ladder disallows."""


# Operator-driven transitions (PLANNING §5). Promotion and demotion always
# route via OBSERVE or ASSISTED; the kill switch (``halt``) bypasses this map.
_VALID_TRANSITIONS: dict[AutonomyMode, set[AutonomyMode]] = {
    AutonomyMode.OBSERVE: {AutonomyMode.PAPER, AutonomyMode.ASSISTED},
    AutonomyMode.PAPER: {AutonomyMode.OBSERVE, AutonomyMode.ASSISTED},
    AutonomyMode.ASSISTED: {AutonomyMode.OBSERVE, AutonomyMode.PAPER},
    AutonomyMode.SEMI_AUTO: {AutonomyMode.OBSERVE, AutonomyMode.ASSISTED},
    AutonomyMode.SUPERVISED: {AutonomyMode.OBSERVE, AutonomyMode.ASSISTED},
}


class ModeController:
    def __init__(self, bus: Bus, initial: AutonomyMode = AutonomyMode.OBSERVE) -> None:
        self._bus = bus
        self._mode = initial

    @property
    def current(self) -> AutonomyMode:
        return self._mode

    def can_transition(self, to: AutonomyMode) -> bool:
        """True if ``to`` is a permitted operator transition from the current mode."""
        return to in _VALID_TRANSITIONS.get(self._mode, set())

    async def set(
        self, to: AutonomyMode, *, actor: str = "operator", reason: str = ""
    ) -> AutonomyMode:
        """Apply an operator mode transition, publishing ``system.mode_changed``.

        Idempotent: setting the current mode is a no-op and emits no event.
        Raises :class:`InvalidModeTransition` for a disallowed move. The value
        is updated before the event is published so a subscriber reading
        ``current`` during fan-out already sees the new mode.
        """
        previous = self._mode
        if to == previous:
            return previous
        if to not in _VALID_TRANSITIONS.get(previous, set()):
            raise InvalidModeTransition(
                f"cannot transition from {previous.value!r} to {to.value!r}"
            )
        self._mode = to
        await self._publish_mode_changed(previous, to, actor, reason)
        logger.info("mode.changed", from_mode=previous.value, to_mode=to.value, actor=actor)
        return to

    async def halt(self, *, reason: str = "operator_halt", actor: str = "operator") -> None:
        """Kill switch: force OBSERVE immediately, then publish ``risk.halt``.

        Bypasses transition validation. The value flips to OBSERVE *before* any
        event is published, so a decision in flight is re-validated against
        OBSERVE. Also emits an audited ``system.mode_changed`` when we were not
        already in OBSERVE, keeping the mode timeline complete.
        """
        previous = self._mode
        self._mode = AutonomyMode.OBSERVE
        now = datetime.now(UTC)
        await self._bus.publish(EventEnvelope(
            event_type=EventType.RISK_HALT,
            source=actor,
            event_time=now,
            ingest_time=now,
            payload={"reason": reason, "scope": "all", "actor": actor},
        ))
        if previous != AutonomyMode.OBSERVE:
            await self._publish_mode_changed(previous, AutonomyMode.OBSERVE, actor, reason)
        logger.warning("mode.halted", from_mode=previous.value, reason=reason)

    async def _publish_mode_changed(
        self, previous: AutonomyMode, to: AutonomyMode, actor: str, reason: str
    ) -> None:
        now = datetime.now(UTC)
        await self._bus.publish(EventEnvelope(
            event_type=EventType.SYSTEM_MODE_CHANGED,
            source=actor,
            event_time=now,
            ingest_time=now,
            payload={
                "from_mode": previous.value,
                "to_mode": to.value,
                "actor": actor,
                "reason": reason,
            },
        ))
