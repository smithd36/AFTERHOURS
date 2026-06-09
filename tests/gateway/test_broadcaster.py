"""
Unit tests for Broadcaster.

Uses FakeWebSocket instead of a real FastAPI WebSocket — no ASGI app needed.
Tests cover: fan-out delivery, dead-client pruning, connect/disconnect, lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas import EventEnvelope, EventType
from gateway.broadcaster import Broadcaster


# ---------------------------------------------------------------------------
# Fake WebSocket — satisfies WebSocketLike protocol
# ---------------------------------------------------------------------------


class FakeWebSocket:
    def __init__(self, fail_on_send: bool = False) -> None:
        self.sent: list[str] = []
        self.accepted: bool = False
        self._fail = fail_on_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        if self._fail:
            raise RuntimeError("connection closed")
        self.sent.append(data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(event_type: str = EventType.MARKET_TICK) -> EventEnvelope:
    now = datetime.now(UTC)
    return EventEnvelope(
        event_type=event_type,
        source="test",
        event_time=now,
        ingest_time=now,
        payload={"instrument": "BTC-USD", "price": "65000.00"},
    )


@pytest.fixture
def bus_and_store():
    store = InMemoryEventStore()
    return InProcessBus(store), store


@pytest.fixture
async def broadcaster(bus_and_store):
    bus, _ = bus_and_store
    b = Broadcaster(bus)
    await b.start()
    yield b
    await b.stop()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestBroadcasterLifecycle:
    async def test_start_subscribes_to_bus(self, bus_and_store) -> None:
        bus, _ = bus_and_store
        b = Broadcaster(bus)
        assert b._sub is None
        await b.start()
        assert b._sub is not None
        await b.stop()

    async def test_stop_unsubscribes_from_bus(self, bus_and_store) -> None:
        bus, _ = bus_and_store
        b = Broadcaster(bus)
        await b.start()
        ws = FakeWebSocket()
        await b.connect(ws)

        await b.stop()

        # After stop, bus events must not reach the client
        await bus.publish(_envelope())
        assert ws.sent == []

    async def test_stop_is_idempotent(self, broadcaster: Broadcaster) -> None:
        await broadcaster.stop()
        await broadcaster.stop()  # second call must not raise


# ---------------------------------------------------------------------------
# Connect / disconnect
# ---------------------------------------------------------------------------


class TestClientManagement:
    async def test_connect_accepts_websocket(self, broadcaster: Broadcaster) -> None:
        ws = FakeWebSocket()
        await broadcaster.connect(ws)
        assert ws.accepted is True

    async def test_connect_increments_client_count(self, broadcaster: Broadcaster) -> None:
        assert broadcaster.client_count == 0
        await broadcaster.connect(FakeWebSocket())
        assert broadcaster.client_count == 1
        await broadcaster.connect(FakeWebSocket())
        assert broadcaster.client_count == 2

    async def test_disconnect_decrements_client_count(
        self, broadcaster: Broadcaster
    ) -> None:
        ws = FakeWebSocket()
        await broadcaster.connect(ws)
        broadcaster.disconnect(ws)
        assert broadcaster.client_count == 0

    async def test_disconnect_unknown_client_is_safe(
        self, broadcaster: Broadcaster
    ) -> None:
        broadcaster.disconnect(FakeWebSocket())  # must not raise


# ---------------------------------------------------------------------------
# Fan-out delivery
# ---------------------------------------------------------------------------


class TestFanOut:
    async def test_published_event_reaches_client(
        self, broadcaster: Broadcaster, bus_and_store
    ) -> None:
        bus, _ = bus_and_store
        ws = FakeWebSocket()
        await broadcaster.connect(ws)

        env = _envelope()
        await bus.publish(env)

        assert len(ws.sent) == 1
        import json
        data = json.loads(ws.sent[0])
        assert data["event_type"] == EventType.MARKET_TICK

    async def test_all_clients_receive_event(
        self, broadcaster: Broadcaster, bus_and_store
    ) -> None:
        bus, _ = bus_and_store
        clients = [FakeWebSocket() for _ in range(3)]
        for ws in clients:
            await broadcaster.connect(ws)

        await bus.publish(_envelope())

        for ws in clients:
            assert len(ws.sent) == 1

    async def test_no_clients_is_silent(
        self, broadcaster: Broadcaster, bus_and_store
    ) -> None:
        bus, _ = bus_and_store
        # No clients connected — publish must not raise
        await bus.publish(_envelope())

    async def test_disconnected_client_pruned_on_send_failure(
        self, broadcaster: Broadcaster, bus_and_store
    ) -> None:
        bus, _ = bus_and_store
        bad_ws = FakeWebSocket(fail_on_send=True)
        good_ws = FakeWebSocket()
        await broadcaster.connect(bad_ws)
        await broadcaster.connect(good_ws)

        await bus.publish(_envelope())

        # bad_ws removed from the broadcaster
        assert broadcaster.client_count == 1
        # good_ws still received the event
        assert len(good_ws.sent) == 1

    async def test_multiple_events_delivered_in_order(
        self, broadcaster: Broadcaster, bus_and_store
    ) -> None:
        bus, _ = bus_and_store
        ws = FakeWebSocket()
        await broadcaster.connect(ws)

        types = [
            EventType.MARKET_TICK,
            EventType.SIGNAL_CREATED,
            EventType.DECISION_PROPOSED,
        ]
        for et in types:
            await bus.publish(_envelope(et))

        import json
        received_types = [json.loads(m)["event_type"] for m in ws.sent]
        assert received_types == types

    async def test_payload_survives_serialisation_round_trip(
        self, broadcaster: Broadcaster, bus_and_store
    ) -> None:
        bus, _ = bus_and_store
        ws = FakeWebSocket()
        await broadcaster.connect(ws)

        await bus.publish(_envelope())

        import json
        data = json.loads(ws.sent[0])
        assert data["payload"]["instrument"] == "BTC-USD"
        assert data["payload"]["price"] == "65000.00"
