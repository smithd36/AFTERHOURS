"""
Broadcaster — the bridge between the event bus and connected WebSocket clients.

Subscribes to all bus topics with a "*" pattern and fans every EventEnvelope
out to each connected browser client as a JSON string.

Back-pressure isolation (ADR-001 — the bus must never stall on a consumer):
``_fanout`` runs as a bus subscriber, and ``InProcessBus.publish`` awaits its
subscribers before returning. So this handler must never ``await`` a client
socket directly — a single congested connection would otherwise back-pressure
the publisher, stalling the Kraken dispatch loop and the risk engine's tick
path. Instead each client owns a bounded outbound queue drained by its own
writer task; fan-out is a non-blocking enqueue. A slow or stalled client sheds
messages from *its own* queue (drop-oldest) without blocking any publisher or
any other client. A dead socket is detected by its writer task (the send
raises) and pruned — no longer dependent on a fan-out send to surface it.

Concurrency note: all mutations happen in the asyncio event loop (single-
threaded cooperative multitasking), so no locks are needed. We snapshot the
client map with list() before iterating to guard against changes between awaits.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

import structlog

from core.bus import Bus, Subscription
from core.schemas import EventEnvelope

from .settings import GatewaySettings

logger = structlog.get_logger(__name__)


class WebSocketLike(Protocol):
    """
    Structural protocol satisfied by both FastAPI's WebSocket and test fakes.
    Keeps the broadcaster decoupled from FastAPI's WebSocket type so it can
    be unit-tested without spinning up an ASGI app.
    """

    async def accept(self) -> None: ...

    async def send_text(self, data: str) -> None: ...


class _ClientChannel:
    """A single client's bounded outbound queue plus the writer task draining it.

    ``enqueue`` is synchronous and never blocks: on overflow it drops the oldest
    queued message so a stalled client can't grow its backlog without bound and
    can't slow the publisher. The writer task is the only thing that awaits the
    socket, so a slow send delays only this client.
    """

    def __init__(self, ws: WebSocketLike, maxsize: int) -> None:
        self._ws = ws
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self._task: asyncio.Task[None] | None = None
        self._on_close: object = None
        self.dropped = 0

    def start(self, on_close: object) -> None:
        # on_close() is invoked (once) when the writer exits because its socket
        # failed, so the broadcaster can prune the dead client.
        self._on_close = on_close
        self._task = asyncio.create_task(self._run())

    def enqueue(self, data: str) -> None:
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            # Drop the oldest message for this client only; keep the queue's
            # unfinished-task count balanced so a join() in tests/shutdown still
            # completes.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                self.dropped += 1
            except asyncio.QueueEmpty:  # pragma: no cover — full→empty race
                pass
            self._queue.put_nowait(data)

    async def _run(self) -> None:
        while True:
            data = await self._queue.get()
            try:
                await self._ws.send_text(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Socket is dead (closed connection, network error). Balance the
                # queue counter, ask the broadcaster to prune us, and exit.
                self._queue.task_done()
                callback = self._on_close
                if callable(callback):
                    callback()
                return
            else:
                self._queue.task_done()

    def cancel(self) -> None:
        """Stop the writer task without awaiting (for the sync disconnect path)."""
        if self._task is not None:
            self._task.cancel()

    async def aclose(self) -> None:
        """Stop the writer task and await its teardown (for graceful shutdown)."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


class Broadcaster:
    def __init__(self, bus: Bus, settings: GatewaySettings | None = None) -> None:
        self._bus = bus
        self._settings = settings or GatewaySettings()
        self._clients: dict[WebSocketLike, _ClientChannel] = {}
        self._sub: Subscription | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Subscribe to the bus. Call once during app startup."""
        self._sub = await self._bus.subscribe("*", self._fanout)
        logger.info("broadcaster.started")

    async def stop(self) -> None:
        """Unsubscribe from the bus and tear down all client writer tasks."""
        if self._sub is not None:
            await self._bus.unsubscribe(self._sub)
            self._sub = None
        channels = list(self._clients.values())
        self._clients.clear()
        for channel in channels:
            await channel.aclose()
        logger.info("broadcaster.stopped")

    # ------------------------------------------------------------------
    # Client management
    # ------------------------------------------------------------------

    async def connect(self, ws: WebSocketLike) -> None:
        """Accept and register a new client, starting its writer task."""
        await ws.accept()
        channel = _ClientChannel(ws, maxsize=self._settings.ws_client_queue_size)
        self._clients[ws] = channel
        # Prune this client if its writer exits on a failed send.
        channel.start(on_close=lambda: self._clients.pop(ws, None))
        logger.info("broadcaster.client_connected", total=len(self._clients))

    def disconnect(self, ws: WebSocketLike) -> None:
        """Remove a client (called when the read loop exits)."""
        channel = self._clients.pop(ws, None)
        if channel is not None:
            channel.cancel()
        logger.info("broadcaster.client_disconnected", total=len(self._clients))

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def total_dropped(self) -> int:
        """Messages dropped across all clients due to full outbound queues.

        A non-zero, growing value means at least one client can't keep up with
        the event rate — useful operational signal, not an error on its own.
        """
        return sum(c.dropped for c in self._clients.values())

    # ------------------------------------------------------------------
    # Fan-out (bus handler)
    # ------------------------------------------------------------------

    async def _fanout(self, envelope: EventEnvelope) -> None:
        if not self._clients:
            return

        data = envelope.model_dump_json()
        # Non-blocking: hand each client's writer task the message and return.
        # We never await a socket here, so a slow client cannot stall publish().
        for channel in list(self._clients.values()):  # snapshot before iterating
            channel.enqueue(data)
