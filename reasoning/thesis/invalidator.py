"""
Thesis invalidator.

Subscribes to thesis.created to track active theses. Runs a background
loop every minute to expire theses whose time_horizon_hours has elapsed,
emitting thesis.invalidated with reason="expired".

Programmatic condition evaluation (e.g. "price drops below X") is Phase 3+.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.events import EventEnvelope, EventType

if TYPE_CHECKING:
    from core.bus.store import EventStore

logger = structlog.get_logger(__name__)

_CHECK_INTERVAL_SECONDS = 60
# How far back to rehydrate active theses on restart. Active theses are bounded
# (cooldown per instrument × expiry window), so this comfortably covers them.
# ponytail: bump if a very large watchlist ever exceeds it.
_REHYDRATE_LIMIT = 500


class ThesisInvalidator:
    def __init__(self, bus: Bus, store: EventStore | None = None) -> None:
        self._bus = bus
        # The event store lets us rebuild _active after a restart; without it
        # (unit tests) rehydration is a no-op and only live theses are tracked.
        self._store = store
        self._sub: Subscription | None = None
        self._task: asyncio.Task[None] | None = None
        # thesis_id → (expiry_time, instrument)
        self._active: dict[UUID, tuple[datetime, str]] = {}

    async def start(self) -> None:
        # Subscribe before rehydrating so a thesis created during rehydration
        # isn't missed; both paths key by thesis_id, so a double-add is harmless.
        self._sub = await self._bus.subscribe(EventType.THESIS_CREATED, self._handle_thesis)
        await self._rehydrate()
        self._task = asyncio.create_task(self._expiry_loop(), name="thesis_invalidator")
        logger.info("thesis_invalidator.started", tracked=len(self._active))

    async def _rehydrate(self) -> None:
        """Rebuild the active-thesis set from the event store after a restart.

        The _active dict is otherwise in-memory only, so theses created before a
        restart would never expire. Replays recent thesis.created, drops any that
        already have a thesis.invalidated, and re-arms the rest. Expiry is anchored
        on event_time (two-clock rule); theses already past expiry fire on the next
        loop tick.
        """
        if self._store is None:
            return
        envelopes = await self._store.recent(
            [EventType.THESIS_CREATED.value, EventType.THESIS_INVALIDATED.value],
            limit=_REHYDRATE_LIMIT,
        )
        invalidated: set[UUID] = set()
        created: dict[UUID, tuple[datetime, str]] = {}
        for env in envelopes:
            p = env.payload
            if env.event_type == EventType.THESIS_INVALIDATED.value:
                tid = p.get("thesis_id")
                if tid:
                    invalidated.add(UUID(str(tid)))
            elif env.event_type == EventType.THESIS_CREATED.value:
                raw = p.get("id")
                if raw:
                    horizon = int(p.get("time_horizon_hours", 8))
                    created[UUID(str(raw))] = (
                        env.event_time + timedelta(hours=horizon),
                        str(p.get("instrument", "")),
                    )
        self._active.update({tid: v for tid, v in created.items() if tid not in invalidated})

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._sub is not None:
            await self._bus.unsubscribe(self._sub)
            self._sub = None
        logger.info("thesis_invalidator.stopped")

    async def _handle_thesis(self, envelope: EventEnvelope) -> None:
        p = envelope.payload
        raw_id = p.get("id")
        if not raw_id:
            return
        thesis_id = UUID(str(raw_id))
        horizon = int(p.get("time_horizon_hours", 8))
        # Anchor expiry on the source clock (two-clock rule), so it matches the
        # rehydrated value and stays correct under event replay.
        expiry = envelope.event_time + timedelta(hours=horizon)
        self._active[thesis_id] = (expiry, str(p.get("instrument", "")))

    async def _expiry_loop(self) -> None:
        while True:
            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
            now = datetime.now(UTC)
            expired = [tid for tid, (exp, _) in self._active.items() if exp <= now]
            for thesis_id in expired:
                _, instrument = self._active.pop(thesis_id)
                await self._bus.publish(EventEnvelope(
                    event_type=EventType.THESIS_INVALIDATED,
                    source="thesis_invalidator",
                    event_time=now,
                    ingest_time=now,
                    payload={
                        "thesis_id": str(thesis_id),
                        "reason": "expired",
                        "instrument": instrument,
                    },
                ))
                logger.info("thesis.expired", thesis_id=str(thesis_id), instrument=instrument)
