"""
FastAPI gateway — HTTP + WebSocket server.

The gateway is the single entry point for the browser:
  GET  /api/health       — liveness probe
  GET  /api/status       — system status snapshot
  WS   /ws               — real-time event stream (bus → browser)

WebSocket protocol:
  Server → client: EventEnvelope serialised as JSON (one object per message).
  Client → server: ignored for now; reserved for future commands/filters.

Dev usage:
  uvicorn gateway.app:app --reload --port 8000

The Vite dev server proxies /api and /ws to this port (vite.config.ts),
so the frontend never needs CORS headers in development.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.bus import InProcessBus
from core.bus.store import SqliteEventStore
from core.db import migrate, open_db
from core.logging import configure_logging
from ingestion.coinbase import CoinbaseFeed

from .broadcaster import Broadcaster
from .settings import GatewaySettings

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Default lifespan (production)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def default_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    logger.info("gateway.starting")

    conn = await open_db()
    await migrate(conn)

    store = SqliteEventStore(conn)
    bus = InProcessBus(store)

    broadcaster = Broadcaster(bus)
    await broadcaster.start()

    feed = CoinbaseFeed(bus)
    feed_task = asyncio.create_task(feed.run(), name="coinbase_feed")

    # Store on app.state so route handlers can access them.
    app.state.bus = bus
    app.state.broadcaster = broadcaster
    app.state.conn = conn
    app.state.feed_task = feed_task

    logger.info("gateway.ready")
    yield  # ← app serves requests here

    logger.info("gateway.shutting_down")

    feed_task.cancel()
    try:
        await feed_task
    except asyncio.CancelledError:
        pass

    await broadcaster.stop()
    await bus.close()
    await conn.close()

    logger.info("gateway.stopped")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(lifespan: Any = default_lifespan) -> FastAPI:
    """
    Returns a configured FastAPI application.

    Pass a custom lifespan in tests to avoid starting real feeds and DB.

        app = create_app(lifespan=test_lifespan)
    """
    settings = GatewaySettings()

    app = FastAPI(
        title="AFTERHOURS",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        broadcaster: Broadcaster = app.state.broadcaster
        return {
            "status": "ok",
            "timestamp": datetime.now(UTC).isoformat(),
            "connected_clients": broadcaster.client_count,
        }

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        broadcaster: Broadcaster = websocket.app.state.broadcaster
        await broadcaster.connect(websocket)
        try:
            while True:
                # Read loop: keeps the connection alive and detects disconnect.
                # Reserved for future client→server messages (filters, commands).
                await websocket.receive_text()
        except WebSocketDisconnect:
            broadcaster.disconnect(websocket)
        except Exception:
            # Catch-all: any unexpected error also cleans up the client.
            broadcaster.disconnect(websocket)


# ---------------------------------------------------------------------------
# Module-level app instance — loaded by uvicorn
# ---------------------------------------------------------------------------

app = create_app()
