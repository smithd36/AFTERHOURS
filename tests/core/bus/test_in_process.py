"""
Unit tests for InProcessBus and pattern matching.

All tests use InMemoryEventStore — no Postgres required.
PostgresEventStore is covered by integration tests (not in this file).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.bus.in_process import InProcessBus, _matches
from core.bus.store import InMemoryEventStore
from core.schemas import EventEnvelope, EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(event_type: str) -> EventEnvelope:
    now = datetime.now(UTC)
    return EventEnvelope(
        event_type=event_type,
        source="test",
        event_time=now,
        ingest_time=now,
        payload={},
    )


@pytest.fixture
def store() -> InMemoryEventStore:
    return InMemoryEventStore()


@pytest.fixture
def bus(store: InMemoryEventStore) -> InProcessBus:
    return InProcessBus(store)


# ---------------------------------------------------------------------------
# Pattern matching (pure, no I/O)
# ---------------------------------------------------------------------------


class TestPatternMatching:
    def test_exact_match(self) -> None:
        assert _matches("decision.proposed", "decision.proposed")

    def test_exact_no_match(self) -> None:
        assert not _matches("decision.proposed", "decision.approved")

    def test_prefix_wildcard_matches_subtypes(self) -> None:
        assert _matches("decision.*", "decision.proposed")
        assert _matches("decision.*", "decision.approved")
        assert _matches("decision.*", "decision.executed")

    def test_prefix_wildcard_requires_dot_separator(self) -> None:
        # "market.*" must NOT match "marketdata" — domains are dot-delimited
        assert not _matches("market.*", "marketdata")

    def test_prefix_wildcard_does_not_match_sibling_domain(self) -> None:
        assert not _matches("decision.*", "portfolio.updated")
        assert not _matches("decision.*", "signal.created")

    def test_global_wildcard_matches_everything(self) -> None:
        for et in [
            EventType.SIGNAL_CREATED,
            EventType.DECISION_PROPOSED,
            EventType.RISK_HALT,
            EventType.SYSTEM_ERROR,
        ]:
            assert _matches("*", et)

    def test_exact_match_prefix_domain(self) -> None:
        # "decision" alone is not a valid wildcard — must end with .*
        assert not _matches("decision", "decision.proposed")


# ---------------------------------------------------------------------------
# InProcessBus behaviour
# ---------------------------------------------------------------------------


class TestInProcessBus:
    async def test_publish_persists_to_store(
        self, bus: InProcessBus, store: InMemoryEventStore
    ) -> None:
        env = _envelope(EventType.SIGNAL_CREATED)
        await bus.publish(env)
        assert len(store.events) == 1
        assert store.events[0].id == env.id

    async def test_publish_persists_before_fanout(
        self, store: InMemoryEventStore
    ) -> None:
        """Handler must see the event already in the store when it fires."""
        seen_in_store: list[bool] = []

        async def handler(env: EventEnvelope) -> None:
            seen_in_store.append(env.id in {e.id for e in store.events})

        bus = InProcessBus(store)
        await bus.subscribe("*", handler)
        await bus.publish(_envelope(EventType.SIGNAL_CREATED))
        assert seen_in_store == [True]

    async def test_subscriber_called_on_matching_event(
        self, bus: InProcessBus
    ) -> None:
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe(EventType.SIGNAL_CREATED, handler)
        env = _envelope(EventType.SIGNAL_CREATED)
        await bus.publish(env)

        assert len(received) == 1
        assert received[0].id == env.id

    async def test_subscriber_not_called_on_non_matching_event(
        self, bus: InProcessBus
    ) -> None:
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe(EventType.DECISION_PROPOSED, handler)
        await bus.publish(_envelope(EventType.SIGNAL_CREATED))

        assert received == []

    async def test_prefix_wildcard_subscription(self, bus: InProcessBus) -> None:
        received: list[str] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env.event_type)

        await bus.subscribe("decision.*", handler)
        await bus.publish(_envelope(EventType.DECISION_PROPOSED))
        await bus.publish(_envelope(EventType.DECISION_APPROVED))
        await bus.publish(_envelope(EventType.SIGNAL_CREATED))  # must not match

        assert received == [EventType.DECISION_PROPOSED, EventType.DECISION_APPROVED]

    async def test_global_wildcard_receives_all(self, bus: InProcessBus) -> None:
        received: list[str] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env.event_type)

        await bus.subscribe("*", handler)
        await bus.publish(_envelope(EventType.SIGNAL_CREATED))
        await bus.publish(_envelope(EventType.DECISION_PROPOSED))
        await bus.publish(_envelope(EventType.RISK_HALT))

        assert received == [
            EventType.SIGNAL_CREATED,
            EventType.DECISION_PROPOSED,
            EventType.RISK_HALT,
        ]

    async def test_multiple_subscribers_all_called(self, bus: InProcessBus) -> None:
        calls: list[str] = []

        async def handler_a(env: EventEnvelope) -> None:
            calls.append("a")

        async def handler_b(env: EventEnvelope) -> None:
            calls.append("b")

        await bus.subscribe("*", handler_a)
        await bus.subscribe("*", handler_b)
        await bus.publish(_envelope(EventType.SIGNAL_CREATED))

        assert set(calls) == {"a", "b"}

    async def test_failing_handler_isolated_from_others(
        self, bus: InProcessBus
    ) -> None:
        good_received: list[EventEnvelope] = []

        async def bad_handler(env: EventEnvelope) -> None:
            raise RuntimeError("handler exploded")

        async def good_handler(env: EventEnvelope) -> None:
            good_received.append(env)

        await bus.subscribe("*", bad_handler)
        await bus.subscribe("*", good_handler)

        # Must not raise even though bad_handler throws
        await bus.publish(_envelope(EventType.SIGNAL_CREATED))

        assert len(good_received) == 1

    async def test_failing_store_prevents_fanout(self) -> None:
        class BrokenStore(InMemoryEventStore):
            async def append(self, envelope: EventEnvelope) -> None:
                raise OSError("disk full")

        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        bus = InProcessBus(BrokenStore())
        await bus.subscribe("*", handler)

        with pytest.raises(OSError, match="disk full"):
            await bus.publish(_envelope(EventType.SIGNAL_CREATED))

        # Persistence failed → handler must NOT have been called
        assert received == []

    async def test_unsubscribe_stops_delivery(self, bus: InProcessBus) -> None:
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        sub = await bus.subscribe("*", handler)
        await bus.publish(_envelope(EventType.SIGNAL_CREATED))
        await bus.unsubscribe(sub)
        await bus.publish(_envelope(EventType.SIGNAL_CREATED))

        assert len(received) == 1

    async def test_close_removes_all_subscribers(self, bus: InProcessBus) -> None:
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe("*", handler)
        await bus.close()
        await bus.publish(_envelope(EventType.SIGNAL_CREATED))

        assert received == []
