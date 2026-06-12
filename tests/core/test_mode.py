"""ModeController — the single source of truth for the autonomy mode."""

from __future__ import annotations

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.mode import InvalidModeTransition, ModeController
from core.schemas.events import AutonomyMode, EventEnvelope, EventType


@pytest.fixture
async def bus() -> InProcessBus:
    return InProcessBus(store=InMemoryEventStore())


async def test_defaults_to_observe(bus: InProcessBus) -> None:
    assert ModeController(bus).current == AutonomyMode.OBSERVE


async def test_set_updates_value_and_publishes_audit_event(bus: InProcessBus) -> None:
    modes = ModeController(bus, initial=AutonomyMode.OBSERVE)
    events: list[EventEnvelope] = []
    await bus.subscribe(EventType.SYSTEM_MODE_CHANGED, lambda e: events.append(e))

    result = await modes.set(AutonomyMode.PAPER, reason="promote")

    assert result == AutonomyMode.PAPER
    assert modes.current == AutonomyMode.PAPER
    assert len(events) == 1
    assert events[0].payload["from_mode"] == "observe"
    assert events[0].payload["to_mode"] == "paper"
    assert events[0].payload["reason"] == "promote"


async def test_set_same_mode_is_noop(bus: InProcessBus) -> None:
    modes = ModeController(bus, initial=AutonomyMode.PAPER)
    events: list[EventEnvelope] = []
    await bus.subscribe(EventType.SYSTEM_MODE_CHANGED, lambda e: events.append(e))

    assert await modes.set(AutonomyMode.PAPER) == AutonomyMode.PAPER
    assert events == []  # idempotent — no event emitted


async def test_invalid_transition_raises_and_leaves_mode_unchanged(bus: InProcessBus) -> None:
    modes = ModeController(bus, initial=AutonomyMode.OBSERVE)
    events: list[EventEnvelope] = []
    await bus.subscribe(EventType.SYSTEM_MODE_CHANGED, lambda e: events.append(e))

    with pytest.raises(InvalidModeTransition):
        await modes.set(AutonomyMode.SEMI_AUTO)  # not reachable from OBSERVE

    assert modes.current == AutonomyMode.OBSERVE
    assert events == []


async def test_value_is_updated_before_event_is_published(bus: InProcessBus) -> None:
    """A subscriber reading `current` during fan-out must already see the new
    mode — the race the controller exists to eliminate."""
    modes = ModeController(bus, initial=AutonomyMode.OBSERVE)
    seen_during_fanout: list[AutonomyMode] = []

    async def _observer(_envelope: EventEnvelope) -> None:
        seen_during_fanout.append(modes.current)

    await bus.subscribe(EventType.SYSTEM_MODE_CHANGED, _observer)
    await modes.set(AutonomyMode.PAPER)

    assert seen_during_fanout == [AutonomyMode.PAPER]


async def test_halt_from_active_mode_forces_observe(bus: InProcessBus) -> None:
    modes = ModeController(bus, initial=AutonomyMode.ASSISTED)
    halts: list[EventEnvelope] = []
    changes: list[EventEnvelope] = []
    await bus.subscribe(EventType.RISK_HALT, lambda e: halts.append(e))
    await bus.subscribe(EventType.SYSTEM_MODE_CHANGED, lambda e: changes.append(e))

    await modes.halt(reason="panic")

    assert modes.current == AutonomyMode.OBSERVE
    assert len(halts) == 1
    assert halts[0].payload["reason"] == "panic"
    # An audited mode-change accompanies the halt when we weren't already OBSERVE.
    assert len(changes) == 1
    assert changes[0].payload["to_mode"] == "observe"


async def test_halt_when_already_observe_emits_only_risk_halt(bus: InProcessBus) -> None:
    modes = ModeController(bus, initial=AutonomyMode.OBSERVE)
    halts: list[EventEnvelope] = []
    changes: list[EventEnvelope] = []
    await bus.subscribe(EventType.RISK_HALT, lambda e: halts.append(e))
    await bus.subscribe(EventType.SYSTEM_MODE_CHANGED, lambda e: changes.append(e))

    await modes.halt()

    assert modes.current == AutonomyMode.OBSERVE
    assert len(halts) == 1
    assert changes == []  # no redundant mode-change when already OBSERVE


async def test_halt_forces_observe_before_publishing(bus: InProcessBus) -> None:
    """During halt fan-out, a risk.halt subscriber already sees OBSERVE — so a
    decision re-validated in that handler is gated correctly."""
    modes = ModeController(bus, initial=AutonomyMode.PAPER)
    seen: list[AutonomyMode] = []
    await bus.subscribe(EventType.RISK_HALT, lambda _e: seen.append(modes.current))

    await modes.halt()

    assert seen == [AutonomyMode.OBSERVE]
