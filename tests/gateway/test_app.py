"""
Tests for the FastAPI app — HTTP endpoints and WebSocket route.

Uses a test lifespan that wires up a real InProcessBus + InMemoryEventStore
but does NOT start the Coinbase feed, so tests run without network access.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.bus import InMemoryEventStore, InProcessBus
from gateway.app import create_app
from gateway.broadcaster import Broadcaster


# ---------------------------------------------------------------------------
# Test lifespan — real bus, no feed, no DB
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    store = InMemoryEventStore()
    bus = InProcessBus(store)
    broadcaster = Broadcaster(bus)
    await broadcaster.start()

    app.state.bus = bus
    app.state.broadcaster = broadcaster
    app.state.event_store = store

    yield

    await broadcaster.stop()
    await bus.close()


@pytest.fixture
def client() -> TestClient:
    app = create_app(lifespan=_lifespan)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_status_is_ok(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert data["status"] == "ok"

    def test_includes_timestamp(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert "timestamp" in data

    def test_timestamp_is_iso8601(self, client: TestClient) -> None:
        from datetime import datetime
        ts = client.get("/api/health").json()["timestamp"]
        datetime.fromisoformat(ts)  # raises if malformed


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


class TestStatusEndpoint:
    def test_returns_200(self, client: TestClient) -> None:
        assert client.get("/api/status").status_code == 200

    def test_includes_connected_clients(self, client: TestClient) -> None:
        data = client.get("/api/status").json()
        assert "connected_clients" in data
        assert data["connected_clients"] == 0


# ---------------------------------------------------------------------------
# Recent events endpoint (panel rehydration)
# ---------------------------------------------------------------------------


class TestRecentEventsEndpoint:
    @staticmethod
    def _publish(client: TestClient, event_type: str, payload: dict) -> None:
        from datetime import UTC, datetime

        from core.schemas import EventEnvelope

        env = EventEnvelope(
            event_type=event_type,
            source="test",
            event_time=datetime.now(UTC),
            ingest_time=datetime.now(UTC),
            payload=payload,
        )
        client.portal.call(client.app.state.bus.publish, env)

    def test_returns_only_requested_types(self, client: TestClient) -> None:
        self._publish(client, "market.tick", {"instrument": "BTC-USD", "price": "1"})
        self._publish(client, "signal.created", {"id": "sig-1"})

        data = client.get("/api/events/recent?types=signal.created").json()
        assert len(data["events"]) == 1
        assert data["events"][0]["event_type"] == "signal.created"

    def test_returns_chronological_order(self, client: TestClient) -> None:
        self._publish(client, "signal.created", {"id": "sig-1"})
        self._publish(client, "signal.created", {"id": "sig-2"})

        data = client.get("/api/events/recent?types=signal.created").json()
        ids = [e["payload"]["id"] for e in data["events"]]
        assert ids == ["sig-1", "sig-2"]

    def test_multiple_types(self, client: TestClient) -> None:
        self._publish(client, "signal.created", {"id": "sig-1"})
        self._publish(client, "thesis.created", {"id": "th-1"})

        data = client.get(
            "/api/events/recent?types=signal.created,thesis.created"
        ).json()
        assert len(data["events"]) == 2

    def test_rejects_unknown_type(self, client: TestClient) -> None:
        resp = client.get("/api/events/recent?types=not.a.topic")
        assert resp.status_code == 422

    def test_respects_limit(self, client: TestClient) -> None:
        for i in range(5):
            self._publish(client, "signal.created", {"id": f"sig-{i}"})

        data = client.get("/api/events/recent?types=signal.created&limit=2").json()
        ids = [e["payload"]["id"] for e in data["events"]]
        assert ids == ["sig-3", "sig-4"]  # newest two, oldest first


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


class TestWebSocketEndpoint:
    def test_ws_accepts_connection(self, client: TestClient) -> None:
        with client.websocket_connect("/ws") as ws:
            # connection accepted — we can reach here without exception
            pass

    def test_bus_event_delivered_over_ws(self, client: TestClient) -> None:
        """Publish to the bus while a client is connected; verify it arrives."""
        import json
        from datetime import UTC, datetime
        from core.schemas import EventEnvelope, EventType

        app = client.app

        with client.websocket_connect("/ws") as ws:
            env = EventEnvelope(
                event_type=EventType.MARKET_TICK,
                source="test",
                event_time=datetime.now(UTC),
                ingest_time=datetime.now(UTC),
                payload={"instrument": "BTC-USD", "price": "65000.00"},
            )
            # Schedule publish on the TestClient's event loop via its anyio portal.
            client.portal.call(app.state.bus.publish, env)

            data = json.loads(ws.receive_text())
            assert data["event_type"] == EventType.MARKET_TICK
            assert data["payload"]["instrument"] == "BTC-USD"
