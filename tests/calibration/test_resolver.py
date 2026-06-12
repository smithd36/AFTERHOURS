"""OutcomeResolver tests — event-time-driven decision scoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from calibration.resolver import OutcomeResolver
from calibration.settings import CalibrationSettings
from core.bus import InMemoryEventStore, InProcessBus
from core.mode import ModeController
from core.schemas.events import AutonomyMode, EventEnvelope, EventType

T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)


def _proposed(
    instrument: str = "BTC-USD",
    side: str = "long",
    horizon: str = "intraday",
    confidence: float = 0.7,
    event_time: datetime = T0,
    thesis_id: str | None = None,
    decision_id: str | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.DECISION_PROPOSED,
        source="test",
        event_time=event_time,
        ingest_time=event_time,
        payload={
            "id": decision_id or str(uuid4()),
            "originating_thesis_id": thesis_id,
            "proposal": {
                "instrument": instrument,
                "side": side,
                "size_usd": "0",
                "time_horizon": horizon,
            },
            "confidence": confidence,
            "status": "proposed",
        },
    )


def _tick(instrument: str, price: str, event_time: datetime) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.MARKET_TICK,
        source="test",
        event_time=event_time,
        ingest_time=event_time,
        payload={"instrument": instrument, "price": price, "volume": "1"},
    )


@pytest.fixture
async def bus() -> InProcessBus:
    return InProcessBus(store=InMemoryEventStore())


@pytest.fixture
async def resolver(bus: InProcessBus) -> OutcomeResolver:
    r = OutcomeResolver(bus, initial_mode=AutonomyMode.OBSERVE)
    await r.start()
    return r


@pytest.fixture
async def resolved(bus: InProcessBus) -> list[EventEnvelope]:
    captured: list[EventEnvelope] = []

    async def _capture(e: EventEnvelope) -> None:
        captured.append(e)

    await bus.subscribe(EventType.DECISION_RESOLVED, _capture)
    return captured


async def test_long_hit_on_horizon(
    bus: InProcessBus,
    resolver: OutcomeResolver,
    resolved: list[EventEnvelope],
) -> None:
    await bus.publish(_proposed(side="long", horizon="intraday"))
    await bus.publish(_tick("BTC-USD", "100", T0 + timedelta(seconds=1)))  # entry
    await bus.publish(_tick("BTC-USD", "110", T0 + timedelta(hours=5)))  # past deadline

    assert len(resolved) == 1
    p = resolved[0].payload
    assert p["hit"] is True
    assert p["resolution_reason"] == "horizon_elapsed"
    assert p["entry_price"] == "100"
    assert p["resolution_price"] == "110"
    assert p["realized_return_pct"] == pytest.approx(10.0)
    assert p["mode_at_proposal"] == "observe"
    assert resolver.pending_count == 0
    # decision.resolved carries the resolving tick's event_time (replay-safe)
    assert resolved[0].event_time == T0 + timedelta(hours=5)


async def test_short_miss_when_price_rises(
    bus: InProcessBus,
    resolver: OutcomeResolver,
    resolved: list[EventEnvelope],
) -> None:
    await bus.publish(_proposed(side="short"))
    await bus.publish(_tick("BTC-USD", "100", T0 + timedelta(seconds=1)))
    await bus.publish(_tick("BTC-USD", "110", T0 + timedelta(hours=5)))

    p = resolved[0].payload
    assert p["hit"] is False
    assert p["realized_return_pct"] == pytest.approx(-10.0)


async def test_short_hit_when_price_falls(
    bus: InProcessBus,
    resolver: OutcomeResolver,
    resolved: list[EventEnvelope],
) -> None:
    await bus.publish(_proposed(side="short"))
    await bus.publish(_tick("BTC-USD", "100", T0 + timedelta(seconds=1)))
    await bus.publish(_tick("BTC-USD", "90", T0 + timedelta(hours=5)))

    assert resolved[0].payload["hit"] is True


async def test_out_of_order_tick_before_proposal_ignored(
    bus: InProcessBus,
    resolver: OutcomeResolver,
    resolved: list[EventEnvelope],
) -> None:
    await bus.publish(_proposed())
    # event_time predates the proposal — must not become the entry price
    await bus.publish(_tick("BTC-USD", "50", T0 - timedelta(minutes=1)))
    await bus.publish(_tick("BTC-USD", "100", T0 + timedelta(seconds=1)))
    await bus.publish(_tick("BTC-USD", "110", T0 + timedelta(hours=5)))

    assert resolved[0].payload["entry_price"] == "100"


async def test_no_tick_in_window_drops_unscoreable(
    bus: InProcessBus,
    resolver: OutcomeResolver,
    resolved: list[EventEnvelope],
) -> None:
    await bus.publish(_proposed())
    assert resolver.pending_count == 1
    # First tick arrives after the deadline — nothing to score against.
    await bus.publish(_tick("BTC-USD", "110", T0 + timedelta(hours=5)))

    assert resolved == []
    assert resolver.pending_count == 0


async def test_other_instrument_does_not_resolve(
    bus: InProcessBus,
    resolver: OutcomeResolver,
    resolved: list[EventEnvelope],
) -> None:
    await bus.publish(_proposed(instrument="BTC-USD"))
    await bus.publish(_tick("ETH-USD", "100", T0 + timedelta(seconds=1)))
    await bus.publish(_tick("ETH-USD", "110", T0 + timedelta(hours=5)))

    assert resolved == []
    assert resolver.pending_count == 1


async def test_stop_breach_resolves_early(
    bus: InProcessBus,
    resolver: OutcomeResolver,
    resolved: list[EventEnvelope],
) -> None:
    envelope = _proposed(side="long")
    decision_id = envelope.payload["id"]
    await bus.publish(envelope)
    await bus.publish(_tick("BTC-USD", "100", T0 + timedelta(seconds=1)))

    # Risk engine approves with a stop at 97
    await bus.publish(EventEnvelope(
        event_type=EventType.DECISION_APPROVED,
        source="test",
        event_time=T0 + timedelta(seconds=2),
        ingest_time=T0 + timedelta(seconds=2),
        payload={"id": decision_id, "risk": {"stop_price": "97"}},
    ))
    await bus.publish(_tick("BTC-USD", "96", T0 + timedelta(minutes=10)))  # before deadline

    assert len(resolved) == 1
    p = resolved[0].payload
    assert p["resolution_reason"] == "stop_breached"
    assert p["hit"] is False


async def test_thesis_invalidation_resolves_at_last_price(
    bus: InProcessBus,
    resolver: OutcomeResolver,
    resolved: list[EventEnvelope],
) -> None:
    thesis_id = str(uuid4())
    await bus.publish(_proposed(side="long", thesis_id=thesis_id))
    await bus.publish(_tick("BTC-USD", "100", T0 + timedelta(seconds=1)))
    await bus.publish(_tick("BTC-USD", "104", T0 + timedelta(minutes=30)))

    await bus.publish(EventEnvelope(
        event_type=EventType.THESIS_INVALIDATED,
        source="test",
        event_time=T0 + timedelta(minutes=31),
        ingest_time=T0 + timedelta(minutes=31),
        payload={"thesis_id": thesis_id, "reason": "expired", "instrument": "BTC-USD"},
    ))

    assert len(resolved) == 1
    p = resolved[0].payload
    assert p["resolution_reason"] == "thesis_invalidated"
    assert p["resolution_price"] == "104"
    assert p["hit"] is True


async def test_mode_change_stamps_new_mode(
    bus: InProcessBus,
    resolved: list[EventEnvelope],
) -> None:
    """A proposal is stamped with the live mode read from the shared controller,
    so promoting it before the proposal flows through to mode_at_proposal."""
    modes = ModeController(bus, initial=AutonomyMode.OBSERVE)
    resolver = OutcomeResolver(bus, modes=modes)
    await resolver.start()

    await modes.set(AutonomyMode.PAPER)
    await bus.publish(_proposed())
    await bus.publish(_tick("BTC-USD", "100", T0 + timedelta(seconds=1)))
    await bus.publish(_tick("BTC-USD", "110", T0 + timedelta(hours=5)))

    assert resolved[0].payload["mode_at_proposal"] == "paper"

    await resolver.stop()


async def test_seed_and_replay_catch_up(
    bus: InProcessBus,
    resolved: list[EventEnvelope],
) -> None:
    """Restart path: seed unresolved proposals, replay stored tick history."""
    resolver = OutcomeResolver(bus, initial_mode=AutonomyMode.OBSERVE)
    proposal = _proposed(side="long")
    resolver.seed([(proposal, AutonomyMode.OBSERVE)])
    assert resolver.pending_count == 1

    await resolver.replay([
        _tick("BTC-USD", "100", T0 + timedelta(seconds=1)),
        _tick("BTC-USD", "108", T0 + timedelta(hours=5)),
    ])
    await resolver.start()

    assert len(resolved) == 1
    assert resolved[0].payload["hit"] is True
    assert resolved[0].payload["mode_at_proposal"] == "observe"
    assert resolver.pending_count == 0


async def test_scalp_horizon_uses_minutes(
    bus: InProcessBus,
    resolver: OutcomeResolver,
    resolved: list[EventEnvelope],
) -> None:
    settings = CalibrationSettings()
    await bus.publish(_proposed(horizon="scalp"))
    await bus.publish(_tick("BTC-USD", "100", T0 + timedelta(seconds=1)))
    just_before = T0 + timedelta(minutes=settings.horizon_scalp_minutes - 1)
    await bus.publish(_tick("BTC-USD", "101", just_before))
    assert resolved == []  # deadline not reached
    deadline = T0 + timedelta(minutes=settings.horizon_scalp_minutes)
    await bus.publish(_tick("BTC-USD", "102", deadline))
    assert len(resolved) == 1
