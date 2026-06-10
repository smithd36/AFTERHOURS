"""
Calibration engine — the north-star metric (PLANNING §1.5).

Consumes decision.resolved events and continuously answers: does the
system's stated confidence match realized outcomes? Produces a reliability
table (confidence buckets vs hit rate) and ECE (Expected Calibration
Error), overall and segmented by the autonomy mode each decision was
proposed under — the Appendix B gates each draw on a specific segment.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.events import EventEnvelope, EventType

from .settings import CalibrationSettings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ResolvedSample:
    confidence: float
    hit: bool
    mode: str  # autonomy mode at proposal time
    resolved_at: datetime


def compute_ece(samples: Sequence[ResolvedSample], bucket_count: int) -> float | None:
    """ECE = Σ (nᵢ/N) · |mean confidenceᵢ − hit rateᵢ| over confidence buckets."""
    n = len(samples)
    if n == 0:
        return None
    ece = 0.0
    for in_bucket in _bucketed(samples, bucket_count):
        bn = len(in_bucket)
        if bn == 0:
            continue
        avg_conf = sum(s.confidence for s in in_bucket) / bn
        hit_rate = sum(1 for s in in_bucket if s.hit) / bn
        ece += (bn / n) * abs(avg_conf - hit_rate)
    return ece


def _bucketed(
    samples: Sequence[ResolvedSample], bucket_count: int
) -> list[list[ResolvedSample]]:
    buckets: list[list[ResolvedSample]] = [[] for _ in range(bucket_count)]
    for s in samples:
        index = min(int(s.confidence * bucket_count), bucket_count - 1)
        buckets[index].append(s)
    return buckets


class CalibrationEngine:
    def __init__(self, bus: Bus, settings: CalibrationSettings | None = None) -> None:
        self._bus = bus
        self._settings = settings or CalibrationSettings()
        self._samples: list[ResolvedSample] = []
        self._sub: Subscription | None = None

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(EventType.DECISION_RESOLVED, self._handle_resolved)
        logger.info("calibration_engine.started", samples=len(self._samples))

    async def stop(self) -> None:
        if self._sub is not None:
            await self._bus.unsubscribe(self._sub)
            self._sub = None
        logger.info("calibration_engine.stopped")

    def seed(self, envelopes: Iterable[EventEnvelope]) -> None:
        """Rehydrate from decision.resolved history in the event store."""
        for envelope in envelopes:
            self._record(envelope)

    async def _handle_resolved(self, envelope: EventEnvelope) -> None:
        self._record(envelope)

    def _record(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        try:
            confidence = float(payload["confidence"])
            hit = bool(payload["hit"])
        except (KeyError, TypeError, ValueError):
            return
        self._samples.append(
            ResolvedSample(
                confidence=confidence,
                hit=hit,
                mode=str(payload.get("mode_at_proposal", "observe")),
                resolved_at=envelope.event_time,
            )
        )

    def samples(self, modes: set[str] | None = None) -> list[ResolvedSample]:
        if modes is None:
            return list(self._samples)
        return [s for s in self._samples if s.mode in modes]

    def report(self) -> dict[str, Any]:
        by_mode = {
            mode: self._stats([s for s in self._samples if s.mode == mode])
            for mode in sorted({s.mode for s in self._samples})
        }
        return {"overall": self._stats(self._samples), "by_mode": by_mode}

    def _stats(self, samples: Sequence[ResolvedSample]) -> dict[str, Any]:
        bucket_count = self._settings.ece_buckets
        ece = compute_ece(samples, bucket_count)
        buckets: list[dict[str, Any]] = []
        for i, in_bucket in enumerate(_bucketed(samples, bucket_count)):
            bn = len(in_bucket)
            buckets.append(
                {
                    "lo": i / bucket_count,
                    "hi": (i + 1) / bucket_count,
                    "n": bn,
                    "avg_confidence": (
                        sum(s.confidence for s in in_bucket) / bn if bn else None
                    ),
                    "hit_rate": (sum(1 for s in in_bucket if s.hit) / bn if bn else None),
                }
            )
        return {
            "n": len(samples),
            "ece": round(ece, 4) if ece is not None else None,
            "buckets": buckets,
        }
