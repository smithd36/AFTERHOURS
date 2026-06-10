"""
Autonomy graduation gate tracker (PLANNING Appendix B, Balanced profile).

Evaluates the measurable criteria for the next-mode transitions against
live calibration data. Criteria the system cannot measure yet (regime
coverage, Sharpe floor, kill-switch drill, operator reject rate) are
listed under "deferred" rather than silently passed — graduation remains
an operator decision informed by this report, never an automatic one.
"""

from __future__ import annotations

from typing import Any

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.events import EventEnvelope, EventType

from .engine import CalibrationEngine, ResolvedSample, compute_ece
from .settings import CalibrationSettings

logger = structlog.get_logger(__name__)

# Pre-live, ASSISTED-mode decisions still fill on the paper executor, so
# they count toward the paper sample (PLANNING §5 modes 2–3).
_PAPER_MODES = {"paper", "assisted"}


def _criterion(
    name: str, required: str, current: str, passed: bool
) -> dict[str, Any]:
    return {"name": name, "required": required, "current": current, "passed": passed}


class GateTracker:
    def __init__(
        self,
        bus: Bus,
        engine: CalibrationEngine,
        settings: CalibrationSettings | None = None,
    ) -> None:
        self._bus = bus
        self._engine = engine
        self._settings = settings or CalibrationSettings()
        self._limit_breaches = 0
        self._sub: Subscription | None = None

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(EventType.RISK_LIMIT_BREACHED, self._handle_breach)
        logger.info("gate_tracker.started")

    async def stop(self) -> None:
        if self._sub is not None:
            await self._bus.unsubscribe(self._sub)
            self._sub = None
        logger.info("gate_tracker.stopped")

    async def _handle_breach(self, envelope: EventEnvelope) -> None:
        self._limit_breaches += 1

    def report(self) -> dict[str, Any]:
        return {
            "observe_to_paper": self._observe_to_paper(),
            "paper_to_assisted": self._paper_to_assisted(),
        }

    def _observe_to_paper(self) -> dict[str, Any]:
        s = self._settings
        shadow = self._engine.samples({"observe"})
        ece = compute_ece(shadow, s.ece_buckets)
        criteria = [
            _criterion(
                "resolved_shadow_decisions",
                f">= {s.gate_observe_min_sample}",
                str(len(shadow)),
                len(shadow) >= s.gate_observe_min_sample,
            ),
            _criterion(
                "ece",
                f"<= {s.gate_observe_max_ece}",
                f"{ece:.4f}" if ece is not None else "no sample",
                ece is not None and ece <= s.gate_observe_max_ece,
            ),
        ]
        return self._verdict(criteria, deferred=["regime_coverage >= 1"])

    def _paper_to_assisted(self) -> dict[str, Any]:
        s = self._settings
        paper = self._engine.samples(_PAPER_MODES)
        ece = compute_ece(paper, s.ece_buckets)
        span_days = _span_days(paper)
        criteria = [
            _criterion(
                "resolved_paper_decisions",
                f">= {s.gate_paper_min_sample}",
                str(len(paper)),
                len(paper) >= s.gate_paper_min_sample,
            ),
            _criterion(
                "sample_span_days",
                f">= {s.gate_paper_min_days}",
                f"{span_days:.1f}",
                span_days >= s.gate_paper_min_days,
            ),
            _criterion(
                "ece",
                f"<= {s.gate_paper_max_ece}",
                f"{ece:.4f}" if ece is not None else "no sample",
                ece is not None and ece <= s.gate_paper_max_ece,
            ),
            _criterion(
                "risk_limit_breaches",
                "== 0",
                str(self._limit_breaches),
                self._limit_breaches == 0,
            ),
        ]
        return self._verdict(
            criteria,
            deferred=[
                "regime_coverage >= 2",
                "sharpe > 0 net of modeled fees + slippage",
                "kill-switch drill passed",
                "secrets hardened + reconciliation clean",
            ],
        )

    @staticmethod
    def _verdict(criteria: list[dict[str, Any]], deferred: list[str]) -> dict[str, Any]:
        return {
            "ready": all(c["passed"] for c in criteria),
            "criteria": criteria,
            "deferred": deferred,  # not yet measurable — operator judgement required
        }


def _span_days(samples: list[ResolvedSample]) -> float:
    if len(samples) < 2:
        return 0.0
    times = [s.resolved_at for s in samples]
    return (max(times) - min(times)).total_seconds() / 86400
