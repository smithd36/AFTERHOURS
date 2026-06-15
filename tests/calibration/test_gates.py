"""GateTracker tests — autonomy graduation evidence that must survive restarts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from calibration.engine import CalibrationEngine
from calibration.gates import GateTracker, economic_metrics
from calibration.settings import CalibrationSettings
from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType


@dataclass
class _FakeBook:
    """Structurally satisfies the TradeBook protocol the economic gate reads."""

    realized_trades: list[Decimal] = field(default_factory=list)
    initial_cash: Decimal = Decimal("10000")


@pytest.fixture
async def bus() -> InProcessBus:
    return InProcessBus(store=InMemoryEventStore())


def _breach(instrument: str = "BTC-USD", reason: str = "exposure_cap") -> EventEnvelope:
    """A genuine hard-limit breach (counts toward the gate). Default reason is a
    hypothetical post-fill cap — no such event is emitted today, but the tracker's
    counting logic must handle one when it exists (see docs option B)."""
    now = datetime.now(UTC)
    return EventEnvelope(
        event_type=EventType.RISK_LIMIT_BREACHED,
        source="risk_engine",
        event_time=now,
        ingest_time=now,
        payload={"instrument": instrument, "reason": reason},
    )


def _breach_count(tracker: GateTracker) -> str:
    """The risk_limit_breaches criterion's reported current value."""
    criteria = tracker.report()["paper_to_assisted"]["criteria"]
    return next(c["current"] for c in criteria if c["name"] == "risk_limit_breaches")


async def test_seed_restores_breach_count(bus: InProcessBus) -> None:
    """Persisted breaches must be restored, not forgotten — a reset count would
    silently pass the '0 breaches' gate after a restart."""
    tracker = GateTracker(bus, CalibrationEngine(bus))
    tracker.seed([_breach(), _breach()])
    await tracker.start()

    assert _breach_count(tracker) == "2"

    # A live breach after seeding accumulates on top, not double-counted.
    await bus.publish(_breach())
    assert _breach_count(tracker) == "3"

    await tracker.stop()


async def test_unseeded_tracker_starts_at_zero(bus: InProcessBus) -> None:
    tracker = GateTracker(bus, CalibrationEngine(bus))
    await tracker.start()
    assert _breach_count(tracker) == "0"
    await tracker.stop()


async def test_stop_loss_closes_are_not_counted(bus: InProcessBus) -> None:
    """Stop-loss is the safety mechanism working, not a hard-limit breach — it
    must not block Paper → Assisted, whether seeded or live."""
    tracker = GateTracker(bus, CalibrationEngine(bus))
    tracker.seed([_breach(reason="stop_loss"), _breach(reason="exposure_cap")])
    await tracker.start()

    # Only the genuine breach from the seed counts.
    assert _breach_count(tracker) == "1"

    # A live stop-loss does not increment; a live hard breach does.
    await bus.publish(_breach(reason="stop_loss"))
    assert _breach_count(tracker) == "1"
    await bus.publish(_breach(reason="exposure_cap"))
    assert _breach_count(tracker) == "2"

    await tracker.stop()


# ---------------------------------------------------------------------------
# Economic readiness (Gate 2) — cost-adjusted round-trip P&L
# ---------------------------------------------------------------------------


def _D(*xs: float) -> list[Decimal]:
    return [Decimal(str(x)) for x in xs]


def test_economic_metrics_math() -> None:
    """Expectancy, profit factor and drawdown over a known net-of-fee series."""
    m = economic_metrics(_D(100, -50, 100, -30))
    assert m["trades"] == 4
    assert m["net_pnl"] == Decimal("120")
    assert m["expectancy"] == Decimal("30")  # 120 / 4
    assert m["win_rate"] == 0.5
    assert m["profit_factor"] == Decimal("2.5")  # 200 gross win / 80 gross loss
    # equity curve 100, 50, 150, 120 → worst peak-to-trough is 150→100 = 50
    assert m["max_drawdown"] == Decimal("50")


def test_economic_metrics_no_losses_has_undefined_profit_factor() -> None:
    m = economic_metrics(_D(40, 60))
    assert m["profit_factor"] is None  # no losing trade → undefined (treated as inf)
    assert m["max_drawdown"] == Decimal("0")


def test_economic_metrics_empty() -> None:
    m = economic_metrics([])
    assert m["trades"] == 0
    assert m["expectancy"] is None


def _econ(tracker: GateTracker) -> dict[str, dict[str, object]]:
    """Economic-group criteria from the Paper → Assisted report, keyed by name."""
    return {
        c["name"]: c
        for c in tracker.report()["paper_to_assisted"]["criteria"]
        if c["group"] == "economic"
    }


async def test_economic_gate_blocks_unprofitable_book(bus: InProcessBus) -> None:
    """A net-negative book must fail the economic gate even with enough trades."""
    settings = CalibrationSettings(gate_econ_min_trades=2)
    book = _FakeBook(realized_trades=_D(100, -50, -120))  # net -70
    tracker = GateTracker(bus, CalibrationEngine(bus), settings=settings, trade_book=book)
    econ = _econ(tracker)
    assert econ["closed_trades"]["passed"] is True  # 3 >= 2
    assert econ["net_pnl"]["passed"] is False
    assert econ["expectancy"]["passed"] is False


async def test_economic_gate_passes_profitable_book(bus: InProcessBus) -> None:
    settings = CalibrationSettings(gate_econ_min_trades=2, gate_econ_min_profit_factor=1.1)
    book = _FakeBook(realized_trades=_D(100, -50, 100))  # net 150, PF 4.0
    tracker = GateTracker(bus, CalibrationEngine(bus), settings=settings, trade_book=book)
    econ = _econ(tracker)
    assert all(c["passed"] for c in econ.values())


async def test_economic_gate_absent_without_trade_book(bus: InProcessBus) -> None:
    """No book wired (unit-test path) → no economic criteria, not a silent pass."""
    tracker = GateTracker(bus, CalibrationEngine(bus))
    assert _econ(tracker) == {}
