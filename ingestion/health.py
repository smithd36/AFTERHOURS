"""
Per-feed health reporter → system.feed_healthy / system.feed_degraded events.

Each polling feed owns a FeedHealth. A single-fetch feed reports directly
(report_healthy / report_degraded). A multi-target feed records each external
fetch outcome during a poll cycle (fetch_ok / fetch_failed) and calls commit()
at the end: the cycle is degraded when it attempted at least one fetch and none
succeeded — which catches the silent failure where every per-target request
errors but the poll loop still completes (e.g. USASpending rejecting all
tickers, the bug that prompted this surface).

Events fire ONLY on a status transition, so a healthy feed announces itself once
(operators can see it exists and is up) and a steadily-failing feed doesn't spam
the bus. event_time == ingest_time: feed health is an ops/observability signal,
not a domain event on the venue clock (two-clock rule).
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.bus.base import Bus
from core.schemas.events import EventEnvelope, EventType

_EVENT = {
    "healthy": EventType.SYSTEM_FEED_HEALTHY,
    "degraded": EventType.SYSTEM_FEED_DEGRADED,
}


class FeedHealth:
    def __init__(self, bus: Bus, feed_id: str) -> None:
        self._bus = bus
        self._feed_id = feed_id
        self._status: str | None = None  # None until the first report
        self._ok = 0
        self._fail = 0
        self._last_error = ""

    # --- multi-target feeds: accumulate then commit once per cycle ---

    def fetch_ok(self) -> None:
        self._ok += 1

    def fetch_failed(self, error: str) -> None:
        self._fail += 1
        self._last_error = error or "unknown error"

    async def commit(self) -> None:
        """Emit a transition from this cycle's fetch outcomes, then reset.

        No fetches attempted (e.g. nothing to poll) leaves the status unchanged.
        """
        if self._ok:
            await self.report_healthy()
        elif self._fail:
            await self.report_degraded(self._last_error)
        self._ok = self._fail = 0
        self._last_error = ""

    # --- single-fetch feeds (and the disabled case): report directly ---

    async def report_healthy(self) -> None:
        await self._emit("healthy", "")

    async def report_degraded(self, detail: str) -> None:
        await self._emit("degraded", detail or "unknown error")

    async def _emit(self, status: str, detail: str) -> None:
        if status == self._status:
            return
        self._status = status
        now = datetime.now(UTC)
        await self._bus.publish(
            EventEnvelope(
                event_type=_EVENT[status],
                source=self._feed_id,
                event_time=now,
                ingest_time=now,
                payload={"feed_id": self._feed_id, "status": status, "detail": detail},
            )
        )
