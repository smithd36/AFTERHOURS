"""CalibrationEngine + GateTracker tests — ECE math and gate readiness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from calibration.engine import CalibrationEngine, ResolvedSample, compute_ece
from calibration.gates import GateTracker
from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType

T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _resolved(
    confidence: float,
    hit: bool,
    mode: str = "observe",
    event_time: datetime = T0,
) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.DECISION_RESOLVED,
        source="test",
        event_time=event_time,
        ingest_time=event_time,
        payload={
            "decision_id": "d1",
            "confidence": confidence,
            "hit": hit,
            "mode_at_proposal": mode,
        },
    )


def _samples(confidence: float, hits: list[bool], mode: str = "observe") -> list[ResolvedSample]:
    return [
        ResolvedSample(confidence=confidence, hit=h, mode=mode, resolved_at=T0) for h in hits
    ]


@pytest.fixture
async def bus() -> InProcessBus:
    return InProcessBus(store=InMemoryEventStore())


# ---------------------------------------------------------------------------
# compute_ece
# ---------------------------------------------------------------------------


def test_ece_empty_sample_is_none() -> None:
    assert compute_ece([], 10) is None


def test_ece_perfectly_calibrated() -> None:
    # confidence 0.5, hit rate 0.5 → ECE 0
    samples = _samples(0.5, [True, False, True, False])
    assert compute_ece(samples, 10) == pytest.approx(0.0)


def test_ece_overconfident() -> None:
    # confidence 0.8, hit rate 0.5 → single bucket, ECE = |0.8 − 0.5| = 0.3
    samples = _samples(0.8, [True, False, True, False])
    assert compute_ece(samples, 10) == pytest.approx(0.3)


def test_ece_weighted_across_buckets() -> None:
    # bucket A: 2 samples conf 0.9 all hit → |0.9−1.0| = 0.1
    # bucket B: 2 samples conf 0.3 none hit → |0.3−0.0| = 0.3
    # ECE = 0.5·0.1 + 0.5·0.3 = 0.2
    samples = _samples(0.9, [True, True]) + _samples(0.3, [False, False])
    assert compute_ece(samples, 10) == pytest.approx(0.2)


def test_ece_confidence_one_lands_in_top_bucket() -> None:
    samples = _samples(1.0, [True])
    assert compute_ece(samples, 10) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# CalibrationEngine
# ---------------------------------------------------------------------------


async def test_engine_records_from_bus(bus: InProcessBus) -> None:
    engine = CalibrationEngine(bus)
    await engine.start()

    await bus.publish(_resolved(0.8, True))
    await bus.publish(_resolved(0.8, False))

    report = engine.report()
    assert report["overall"]["n"] == 2
    assert report["overall"]["ece"] == pytest.approx(0.3)
    await engine.stop()


async def test_engine_segments_by_mode(bus: InProcessBus) -> None:
    engine = CalibrationEngine(bus)
    await engine.start()

    await bus.publish(_resolved(0.6, True, mode="observe"))
    await bus.publish(_resolved(0.9, True, mode="paper"))

    report = engine.report()
    assert report["by_mode"]["observe"]["n"] == 1
    assert report["by_mode"]["paper"]["n"] == 1
    assert len(engine.samples({"observe"})) == 1
    assert len(engine.samples()) == 2
    await engine.stop()


async def test_engine_seed_from_history(bus: InProcessBus) -> None:
    engine = CalibrationEngine(bus)
    engine.seed([_resolved(0.7, True), _resolved(0.7, False)])
    assert engine.report()["overall"]["n"] == 2


async def test_engine_ignores_malformed_payload(bus: InProcessBus) -> None:
    engine = CalibrationEngine(bus)
    engine.seed([
        EventEnvelope(
            event_type=EventType.DECISION_RESOLVED,
            source="test",
            event_time=T0,
            ingest_time=T0,
            payload={"decision_id": "d1"},  # no confidence/hit
        )
    ])
    assert engine.report()["overall"]["n"] == 0


# ---------------------------------------------------------------------------
# GateTracker
# ---------------------------------------------------------------------------


async def test_gates_not_ready_below_sample(bus: InProcessBus) -> None:
    engine = CalibrationEngine(bus)
    engine.seed([_resolved(0.5, True), _resolved(0.5, False)])
    tracker = GateTracker(bus, engine)

    gate = tracker.report()["observe_to_paper"]
    assert gate["ready"] is False
    sample = next(c for c in gate["criteria"] if c["name"] == "resolved_shadow_decisions")
    assert sample["passed"] is False
    ece = next(c for c in gate["criteria"] if c["name"] == "ece")
    assert ece["passed"] is True  # perfectly calibrated, just too few


async def test_observe_gate_ready_when_thresholds_met(bus: InProcessBus) -> None:
    engine = CalibrationEngine(bus)
    # 50 perfectly calibrated shadow resolutions (conf 0.5, 50% hits)
    engine.seed([_resolved(0.5, i % 2 == 0, mode="observe") for i in range(50)])
    tracker = GateTracker(bus, engine)

    report = tracker.report()
    assert report["observe_to_paper"]["ready"] is True
    assert report["paper_to_assisted"]["ready"] is False  # no paper sample
    assert report["observe_to_paper"]["deferred"]  # regime coverage still listed


async def test_paper_gate_requires_span_and_no_breaches(bus: InProcessBus) -> None:
    engine = CalibrationEngine(bus)
    # 100 calibrated paper resolutions spread over 15 days
    engine.seed([
        _resolved(0.5, i % 2 == 0, mode="paper", event_time=T0 + timedelta(hours=i * 4))
        for i in range(100)
    ])
    tracker = GateTracker(bus, engine)
    await tracker.start()

    assert tracker.report()["paper_to_assisted"]["ready"] is True

    # A risk limit breach flips the gate
    await bus.publish(EventEnvelope(
        event_type=EventType.RISK_LIMIT_BREACHED,
        source="test",
        event_time=T0,
        ingest_time=T0,
        payload={"limit_type": "stop_loss", "current": "1", "limit": "0"},
    ))
    gate = tracker.report()["paper_to_assisted"]
    assert gate["ready"] is False
    breaches = next(c for c in gate["criteria"] if c["name"] == "risk_limit_breaches")
    assert breaches["current"] == "1"
    await tracker.stop()


async def test_paper_gate_counts_assisted_as_paper(bus: InProcessBus) -> None:
    engine = CalibrationEngine(bus)
    engine.seed([
        _resolved(0.5, i % 2 == 0, mode="assisted", event_time=T0 + timedelta(hours=i * 4))
        for i in range(100)
    ])
    tracker = GateTracker(bus, engine)
    sample = next(
        c
        for c in tracker.report()["paper_to_assisted"]["criteria"]
        if c["name"] == "resolved_paper_decisions"
    )
    assert sample["current"] == "100"
