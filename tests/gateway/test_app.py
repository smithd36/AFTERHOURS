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

from calibration import CalibrationEngine, GateTracker
from core.bus import InMemoryEventStore, InProcessBus
from core.mode import ModeController
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

    calibration_engine = CalibrationEngine(bus)
    await calibration_engine.start()
    gate_tracker = GateTracker(bus, calibration_engine)
    await gate_tracker.start()

    mode_controller = ModeController(bus)

    app.state.bus = bus
    app.state.broadcaster = broadcaster
    app.state.event_store = store
    app.state.calibration_engine = calibration_engine
    app.state.gate_tracker = gate_tracker
    app.state.mode_controller = mode_controller

    yield

    await gate_tracker.stop()
    await calibration_engine.stop()
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


# ---------------------------------------------------------------------------
# Calibration endpoints
# ---------------------------------------------------------------------------


class TestModeEndpoints:
    def test_starts_in_observe(self, client: TestClient) -> None:
        assert client.get("/api/mode").json()["mode"] == "observe"

    def test_set_mode_updates_single_source_of_truth(self, client: TestClient) -> None:
        resp = client.post("/api/mode", json={"mode": "paper"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "paper"
        # Both the read route and the controller object reflect the change — there
        # is only one place the value lives.
        assert client.get("/api/mode").json()["mode"] == "paper"
        assert client.app.state.mode_controller.current.value == "paper"

    def test_invalid_transition_rejected(self, client: TestClient) -> None:
        # observe → semi_auto is not a permitted operator transition.
        resp = client.post("/api/mode", json={"mode": "semi_auto"})
        assert resp.status_code == 422
        assert client.app.state.mode_controller.current.value == "observe"

    def test_same_mode_is_idempotent(self, client: TestClient) -> None:
        resp = client.post("/api/mode", json={"mode": "observe"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "observe"

    def test_halt_forces_observe_and_emits_risk_halt(self, client: TestClient) -> None:
        import json as _json

        client.post("/api/mode", json={"mode": "paper"})
        with client.websocket_connect("/ws") as ws:
            resp = client.post("/api/halt", json={"reason": "panic"})
            assert resp.status_code == 200
            assert resp.json()["mode"] == "observe"
            # The kill switch publishes risk.halt and the controller is now OBSERVE.
            seen = {_json.loads(ws.receive_text())["event_type"] for _ in range(2)}
            assert "risk.halt" in seen
        assert client.app.state.mode_controller.current.value == "observe"


class TestCalibrationEndpoints:
    @staticmethod
    def _publish_resolved(client: TestClient, confidence: float, hit: bool) -> None:
        from datetime import UTC, datetime
        from typing import cast

        from core.schemas import EventEnvelope

        env = EventEnvelope(
            event_type="decision.resolved",
            source="test",
            event_time=datetime.now(UTC),
            ingest_time=datetime.now(UTC),
            payload={
                "decision_id": "d1",
                "confidence": confidence,
                "hit": hit,
                "mode_at_proposal": "observe",
            },
        )
        portal = client.portal
        assert portal is not None
        portal.call(cast(FastAPI, client.app).state.bus.publish, env)

    def test_empty_report(self, client: TestClient) -> None:
        data = client.get("/api/calibration").json()
        assert data["overall"]["n"] == 0
        assert data["overall"]["ece"] is None

    def test_report_reflects_resolved_decisions(self, client: TestClient) -> None:
        self._publish_resolved(client, 0.8, True)
        self._publish_resolved(client, 0.8, False)

        data = client.get("/api/calibration").json()
        assert data["overall"]["n"] == 2
        assert data["overall"]["ece"] == pytest.approx(0.3)
        assert data["by_mode"]["observe"]["n"] == 2

    def test_gates_report_shape(self, client: TestClient) -> None:
        data = client.get("/api/calibration/gates").json()
        for gate in ("observe_to_paper", "paper_to_assisted"):
            assert data[gate]["ready"] is False  # empty sample
            assert data[gate]["criteria"]
            assert data[gate]["deferred"]
