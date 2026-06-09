"""
Tests for ThesisGenerator.

Uses a real InProcessBus and a stub LLMProvider so no network calls are made.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType
from reasoning.llm.base import LLMProvider, Message
from reasoning.thesis import ThesisGenerator
from reasoning.thesis.settings import ThesisSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_RESPONSE = json.dumps({
    "instrument": "BTC-USD",
    "summary": "BTC breakout on high volume",
    "body": "Multiple signals indicate bullish momentum.",
    "direction": "long",
    "confidence": 0.72,
    "invalidation_conditions": ["price drops below 60000"],
    "time_horizon_hours": 6,
})


class StubProvider(LLMProvider):
    def __init__(self, response: str = _VALID_RESPONSE) -> None:
        self._response = response
        self.calls: list[list[Message]] = []

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        self.calls.append(messages)
        return self._response


def _signal(instrument: str, event_time: datetime | None = None) -> EventEnvelope:
    now = event_time or datetime.now(UTC)
    return EventEnvelope(
        event_type=EventType.SIGNAL_CREATED,
        source="test",
        event_time=now,
        ingest_time=now,
        payload={
            "id": "sig-1",
            "type": "price_alert",
            "instruments": [instrument],
            "provenance": {"event_time": now.isoformat(), "ingest_time": now.isoformat()},
            "payload": {"summary": f"{instrument} moved 5%"},
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> InProcessBus:
    return InProcessBus(InMemoryEventStore())


async def test_thesis_emitted_when_enough_signals(bus: InProcessBus) -> None:
    settings = ThesisSettings(min_signals_to_trigger=3, signal_window_minutes=15, cooldown_minutes=60)
    provider = StubProvider()
    generator = ThesisGenerator(bus, provider, settings)
    await generator.start()

    received: list[EventEnvelope] = []
    await bus.subscribe(EventType.THESIS_CREATED, lambda e: received.append(e) or None)  # type: ignore[func-returns-value]

    now = datetime.now(UTC)
    for _ in range(3):
        await bus.publish(_signal("BTC-USD", now))

    await generator.stop()

    assert len(received) == 1
    assert received[0].payload["instrument"] == "BTC-USD"
    assert received[0].payload["direction"] == "long"
    assert provider.calls  # LLM was called


async def test_thesis_not_emitted_below_threshold(bus: InProcessBus) -> None:
    settings = ThesisSettings(min_signals_to_trigger=5, signal_window_minutes=15, cooldown_minutes=60)
    provider = StubProvider()
    generator = ThesisGenerator(bus, provider, settings)
    await generator.start()

    received: list[EventEnvelope] = []
    await bus.subscribe(EventType.THESIS_CREATED, lambda e: received.append(e) or None)  # type: ignore[func-returns-value]

    now = datetime.now(UTC)
    for _ in range(3):
        await bus.publish(_signal("BTC-USD", now))

    await generator.stop()
    assert len(received) == 0


async def test_cooldown_prevents_second_thesis(bus: InProcessBus) -> None:
    settings = ThesisSettings(min_signals_to_trigger=2, signal_window_minutes=15, cooldown_minutes=60)
    provider = StubProvider()
    generator = ThesisGenerator(bus, provider, settings)
    await generator.start()

    received: list[EventEnvelope] = []
    await bus.subscribe(EventType.THESIS_CREATED, lambda e: received.append(e) or None)  # type: ignore[func-returns-value]

    now = datetime.now(UTC)
    # 5 signals — should still only emit 1 thesis (cooldown blocks re-trigger)
    for _ in range(5):
        await bus.publish(_signal("ETH-USD", now))

    await generator.stop()
    assert len(received) == 1


async def test_signals_outside_window_do_not_count(bus: InProcessBus) -> None:
    settings = ThesisSettings(min_signals_to_trigger=3, signal_window_minutes=5, cooldown_minutes=60)
    provider = StubProvider()
    generator = ThesisGenerator(bus, provider, settings)
    await generator.start()

    received: list[EventEnvelope] = []
    await bus.subscribe(EventType.THESIS_CREATED, lambda e: received.append(e) or None)  # type: ignore[func-returns-value]

    old = datetime.now(UTC) - timedelta(minutes=10)
    recent = datetime.now(UTC)
    # 2 old signals + 1 recent = only 1 recent in window → below threshold
    await bus.publish(_signal("BTC-USD", old))
    await bus.publish(_signal("BTC-USD", old))
    await bus.publish(_signal("BTC-USD", recent))

    await generator.stop()
    assert len(received) == 0


async def test_json_retry_on_bad_first_response(bus: InProcessBus) -> None:
    """If the first LLM response is garbage, the generator retries once."""
    call_count = 0

    class RetryProvider(LLMProvider):
        async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "I cannot generate JSON right now."
            return _VALID_RESPONSE

    settings = ThesisSettings(min_signals_to_trigger=2, signal_window_minutes=15, cooldown_minutes=60)
    generator = ThesisGenerator(bus, RetryProvider(), settings)
    await generator.start()

    received: list[EventEnvelope] = []
    await bus.subscribe(EventType.THESIS_CREATED, lambda e: received.append(e) or None)  # type: ignore[func-returns-value]

    now = datetime.now(UTC)
    await bus.publish(_signal("BTC-USD", now))
    await bus.publish(_signal("BTC-USD", now))

    await generator.stop()

    assert call_count == 2
    assert len(received) == 1


async def test_no_emit_on_double_parse_failure(bus: InProcessBus) -> None:
    class BadProvider(LLMProvider):
        async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
            return "not json at all"

    settings = ThesisSettings(min_signals_to_trigger=2, signal_window_minutes=15, cooldown_minutes=60)
    generator = ThesisGenerator(bus, BadProvider(), settings)
    await generator.start()

    received: list[EventEnvelope] = []
    await bus.subscribe(EventType.THESIS_CREATED, lambda e: received.append(e) or None)  # type: ignore[func-returns-value]

    now = datetime.now(UTC)
    await bus.publish(_signal("BTC-USD", now))
    await bus.publish(_signal("BTC-USD", now))

    await generator.stop()
    assert len(received) == 0
