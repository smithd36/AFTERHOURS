"""
Unit tests for Broadcaster.

Uses FakeWebSocket instead of a real FastAPI WebSocket — no ASGI app needed.
Tests cover: fan-out delivery, dead-client pruning, connect/disconnect, lifecycle.
"""

from __future__ import annotations

import asyncio
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
        # When set, send_text blocks until the event is set — simulates a client
        # whose receive buffer is congested (a paused browser tab).
        self.gate: asyncio.Event | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        if self._fail:
            raise RuntimeError("connection closed")
        if self.gate is not None:
            await self.gate.wait()
        self.sent.append(data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _drain(b: Broadcaster) -> None:
    """Wait for every client's writer task to flush its queued messages.

    Delivery is asynchronous now (one writer task per client), so tests that
    assert on what a client received must first let those tasks run.
    """
    for channel in list(b._clients.values()):
        await asyncio.wait_for(channel._queue.join(), timeout=1.0)


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
        await _drain(broadcaster)

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
        await _drain(broadcaster)

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
        await _drain(broadcaster)

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
        await _drain(broadcaster)

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
        await _drain(broadcaster)

        import json
        data = json.loads(ws.sent[0])
        assert data["payload"]["instrument"] == "BTC-USD"
        assert data["payload"]["price"] == "65000.00"


# ---------------------------------------------------------------------------
# Back-pressure isolation — the bug this design fixes
# ---------------------------------------------------------------------------


class TestBackpressureIsolation:
    async def test_slow_client_does_not_block_publish(
        self, broadcaster: Broadcaster, bus_and_store
    ) -> None:
        """A client stalled mid-send must not delay publish() — the publisher
        (Kraken loop / risk engine) returns regardless of client speed."""
        bus, _ = bus_and_store
        slow = FakeWebSocket()
        slow.gate = asyncio.Event()  # never set → its send blocks forever
        await broadcaster.connect(slow)

        # Must complete promptly even though the client's writer is stuck.
        await asyncio.wait_for(bus.publish(_envelope()), timeout=1.0)

        slow.gate.set()  # let the stuck writer finish so teardown is clean

    async def test_slow_client_does_not_block_other_clients(
        self, broadcaster: Broadcaster, bus_and_store
    ) -> None:
        """One congested client must not delay delivery to healthy clients."""
        bus, _ = bus_and_store
        slow = FakeWebSocket()
        slow.gate = asyncio.Event()
        fast = FakeWebSocket()
        await broadcaster.connect(slow)
        await broadcaster.connect(fast)

        await bus.publish(_envelope())
        # The fast client's queue drains independently of the stalled one.
        fast_channel = broadcaster._clients[fast]
        await asyncio.wait_for(fast_channel._queue.join(), timeout=1.0)
        assert len(fast.sent) == 1
        assert slow.sent == []  # still stuck, but harmless

        slow.gate.set()

    async def test_overflow_drops_oldest_for_that_client_only(
        self, bus_and_store
    ) -> None:
        """When a client can't keep up, its queue sheds the oldest messages
        (bounded memory) while other clients are unaffected."""
        bus, _ = bus_and_store
        # Tiny queue so we can overflow it deterministically.
        from gateway.settings import GatewaySettings

        settings = GatewaySettings(ws_client_queue_size=2)
        b = Broadcaster(bus, settings=settings)
        await b.start()

        slow = FakeWebSocket()
        slow.gate = asyncio.Event()  # block the writer so the queue backs up
        await b.connect(slow)

        # First message is pulled by the writer (and blocks on the gate); the
        # next 2 fill the queue; further messages drop the oldest queued ones.
        for _ in range(6):
            await bus.publish(_envelope())

        channel = b._clients[slow]
        assert channel.dropped > 0
        assert channel._queue.qsize() <= 2  # bounded — no unbounded growth
        assert b.total_dropped == channel.dropped

        slow.gate.set()
        await b.stop()
