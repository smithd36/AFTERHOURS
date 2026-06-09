"""
InProcessBus — in-process pub/sub backed by a durable EventStore.

Publish contract (critical — see ADR-001):
  1. Persist first. If the store raises, publish raises and no fan-out occurs.
  2. Fan out concurrently to all matching subscribers.
  3. Handler failures are fully isolated: one bad handler cannot kill others
     or cause publish() to raise. Errors are logged and dropped.

Transport note: this is the Phase 0–3 transport (single process). When
extraction to Redis Streams or NATS JetStream is warranted, replace this
class with an out-of-process implementation that honours the same Bus
interface. Application code never needs to change.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import structlog

from ..schemas import EventEnvelope
from .base import Bus, Handler, Subscription
from .store import EventStore

logger = structlog.get_logger(__name__)


def _matches(pattern: str, event_type: str) -> bool:
    """
    True if event_type satisfies pattern.

    Patterns:
      "*"            — matches everything
      "decision.*"   — matches "decision.proposed", "decision.approved", …
                       does NOT match "decisionsomething" (must be dot-separated)
      "decision.proposed" — exact match only
    """
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-2]  # "decision.*" → "decision"
        return event_type == prefix or event_type.startswith(prefix + ".")
    return pattern == event_type


class InProcessBus(Bus):
    def __init__(self, store: EventStore) -> None:
        self._store = store
        self._subs: list[Subscription] = []
        # Lock guards _subs list; held only during list reads/writes, not during handler calls.
        self._lock = asyncio.Lock()

    async def publish(self, envelope: EventEnvelope) -> None:
        await self._store.append(envelope)  # persist first; raises on failure
        await self._fanout(envelope)

    async def subscribe(self, pattern: str, handler: Handler) -> Subscription:
        sub = Subscription(id=uuid4(), pattern=pattern, handler=handler)
        async with self._lock:
            self._subs.append(sub)
        logger.debug("bus.subscribed", subscription_id=str(sub.id), pattern=pattern)
        return sub

    async def unsubscribe(self, sub: Subscription) -> None:
        async with self._lock:
            self._subs = [s for s in self._subs if s.id != sub.id]
        logger.debug("bus.unsubscribed", subscription_id=str(sub.id))

    async def close(self) -> None:
        async with self._lock:
            self._subs.clear()
        await self._store.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _fanout(self, envelope: EventEnvelope) -> None:
        async with self._lock:
            matching = [s for s in self._subs if _matches(s.pattern, envelope.event_type)]

        if not matching:
            return

        results = await asyncio.gather(
            *[_safe_call(s, envelope) for s in matching],
            return_exceptions=True,
        )

        for sub, result in zip(matching, results):
            if isinstance(result, BaseException):
                logger.error(
                    "bus.handler_error",
                    subscription_id=str(sub.id),
                    pattern=sub.pattern,
                    event_type=envelope.event_type,
                    event_id=str(envelope.id),
                    error=repr(result),
                )


async def _safe_call(sub: Subscription, envelope: EventEnvelope) -> None:
    await sub.handler(envelope)
