"""
Tests for DecisionGenerator — schema validation / range checking of LLM output.

Uses a real InProcessBus and a stub LLMProvider so no network calls are made.
The contract under test (PLANNING §4.5): the assembled decision is validated
against the Decision schema *before* publishing, so out-of-range confidence,
an invalid side, or empty evidence yield no decision.proposed event rather than
a corrupt one that would poison the calibration buckets or diverge state when
Side(...) later raises inside the ledger's fill handler.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.decision import Decision
from core.schemas.events import EventEnvelope, EventType
from reasoning.decision import DecisionGenerator
from reasoning.llm.base import LLMProvider, Message

_SIGNAL_ID = str(uuid4())


def _response(**overrides: object) -> str:
    body: dict[str, object] = {
        "side": "long",
        "order_type": "market",
        "time_horizon": "intraday",
        "reasoning": "Momentum and volume both confirm the breakout.",
        "evidence": [
            {"signal_id": _SIGNAL_ID, "summary": "5% move on volume", "stance": "supporting"}
        ],
        "confidence": 0.7,
    }
    body.update(overrides)
    return json.dumps(body)


class StubProvider(LLMProvider):
    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[list[Message]] = []

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        self.calls.append(messages)
        return self._response


def _thesis(instrument: str = "BTC-USD") -> EventEnvelope:
    now = datetime.now(UTC)
    return EventEnvelope(
        event_type=EventType.THESIS_CREATED,
        source="test",
        event_time=now,
        ingest_time=now,
        payload={
            "id": str(uuid4()),
            "instrument": instrument,
            "status": "active",
            "summary": "BTC breakout",
            "body": "Bullish momentum across signals.",
            "direction": "long",
            "confidence": 0.72,
            "supporting_signal_ids": [_SIGNAL_ID],
        },
    )


@pytest.fixture
def bus() -> InProcessBus:
    return InProcessBus(InMemoryEventStore())


async def _run(bus: InProcessBus, response: str) -> list[EventEnvelope]:
    generator = DecisionGenerator(bus, StubProvider(response))
    await generator.start()
    received: list[EventEnvelope] = []
    await bus.subscribe(
        EventType.DECISION_PROPOSED,
        lambda e: received.append(e) or None,  # type: ignore[func-returns-value]
    )
    await bus.publish(_thesis())
    await generator.stop()
    return received


async def test_valid_response_emits_validated_decision(bus: InProcessBus) -> None:
    received = await _run(bus, _response())
    assert len(received) == 1
    # The published payload must round-trip back through the schema unchanged.
    decision = Decision.model_validate(received[0].payload)
    assert decision.proposal.side.value == "long"
    assert decision.confidence == 0.7
    assert len(decision.evidence) == 1
    # size_usd is the deterministic placeholder; the LLM never sets it.
    assert decision.proposal.size_usd == 0


async def test_out_of_range_confidence_is_rejected(bus: InProcessBus) -> None:
    received = await _run(bus, _response(confidence=7))
    assert received == []


async def test_negative_confidence_is_rejected(bus: InProcessBus) -> None:
    received = await _run(bus, _response(confidence=-0.3))
    assert received == []


async def test_invalid_side_is_rejected(bus: InProcessBus) -> None:
    received = await _run(bus, _response(side="sideways"))
    assert received == []


async def test_empty_evidence_is_rejected(bus: InProcessBus) -> None:
    received = await _run(bus, _response(evidence=[]))
    assert received == []


async def test_evidence_with_unparseable_signal_id_is_dropped_then_rejected(
    bus: InProcessBus,
) -> None:
    # The only evidence item cites a non-UUID id; it is dropped, leaving the
    # evidence list empty, so the decision is rejected (no fabricated trade).
    bad = [{"signal_id": "not-a-uuid", "summary": "x", "stance": "supporting"}]
    received = await _run(bus, _response(evidence=bad))
    assert received == []


async def test_uppercase_side_is_normalised_not_rejected(bus: InProcessBus) -> None:
    received = await _run(bus, _response(side="LONG"))
    assert len(received) == 1
    assert received[0].payload["proposal"]["side"] == "long"
