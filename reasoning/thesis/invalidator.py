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
from uuid import UUID

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.events import EventEnvelope, EventType

logger = structlog.get_logger(__name__)

_CHECK_INTERVAL_SECONDS = 60


class ThesisInvalidator:
    def __init__(self, bus: Bus) -> None:
        self._bus = bus
        self._sub: Subscription | None = None
        self._task: asyncio.Task[None] | None = None
        # thesis_id → (expiry_time, instrument)
        self._active: dict[UUID, tuple[datetime, str]] = {}

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(EventType.THESIS_CREATED, self._handle_thesis)
        self._task = asyncio.create_task(self._expiry_loop(), name="thesis_invalidator")
        logger.info("thesis_invalidator.started")

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
        expiry = envelope.ingest_time + timedelta(hours=horizon)
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
