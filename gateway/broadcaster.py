"""
Broadcaster — the bridge between the event bus and connected WebSocket clients.

Subscribes to all bus topics with a "*" pattern and fans every EventEnvelope
out to each connected browser client as a JSON string.

Concurrency note: all mutations happen in the asyncio event loop (single-
threaded cooperative multitasking), so no locks are needed. We snapshot
_clients with list() before iterating to guard against set changes that
can occur between awaits.
"""

from __future__ import annotations

from typing import Protocol

import structlog

from core.bus import Bus, Subscription
from core.schemas import EventEnvelope

logger = structlog.get_logger(__name__)


class WebSocketLike(Protocol):
    """
    Structural protocol satisfied by both FastAPI's WebSocket and test fakes.
    Keeps the broadcaster decoupled from FastAPI's WebSocket type so it can
    be unit-tested without spinning up an ASGI app.
    """

    async def accept(self) -> None: ...

    async def send_text(self, data: str) -> None: ...


class Broadcaster:
    def __init__(self, bus: Bus) -> None:
        self._bus = bus
        self._clients: set[WebSocketLike] = set()
        self._sub: Subscription | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Subscribe to the bus. Call once during app startup."""
        self._sub = await self._bus.subscribe("*", self._fanout)
        logger.info("broadcaster.started")

    async def stop(self) -> None:
        """Unsubscribe from the bus. Call during app shutdown."""
        if self._sub is not None:
            await self._bus.unsubscribe(self._sub)
            self._sub = None
        logger.info("broadcaster.stopped")

    # ------------------------------------------------------------------
    # Client management
    # ------------------------------------------------------------------

    async def connect(self, ws: WebSocketLike) -> None:
        """Accept and register a new client."""
        await ws.accept()
        self._clients.add(ws)
        logger.info("broadcaster.client_connected", total=len(self._clients))

    def disconnect(self, ws: WebSocketLike) -> None:
        """Remove a client (called when the read loop exits)."""
        self._clients.discard(ws)
        logger.info("broadcaster.client_disconnected", total=len(self._clients))

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ------------------------------------------------------------------
    # Fan-out (bus handler)
    # ------------------------------------------------------------------

    async def _fanout(self, envelope: EventEnvelope) -> None:
        if not self._clients:
            return

        data = envelope.model_dump_json()
        disconnected: set[WebSocketLike] = set()

        for ws in list(self._clients):  # snapshot before iterating
            try:
                await ws.send_text(data)
            except Exception:
                # Any send failure (closed connection, network error) →
                # mark for removal; don't let one dead client block others.
                disconnected.add(ws)

        if disconnected:
            self._clients -= disconnected
            logger.info(
                "broadcaster.pruned_disconnected",
                pruned=len(disconnected),
                remaining=len(self._clients),
            )
