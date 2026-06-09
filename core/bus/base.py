"""
Bus interface — the only coupling point between producers and consumers.

All inter-subsystem communication flows through here. Application code
calls `bus.publish(envelope)` and `bus.subscribe(pattern, handler)` and
never knows which transport is in use (in-process, Redis Streams, NATS).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ..schemas import EventEnvelope

# An async callable that receives an envelope and returns nothing.
Handler = Callable[[EventEnvelope], Coroutine[Any, Any, None]]


@dataclass(frozen=True)
class Subscription:
    """
    Opaque handle returned by subscribe(). Pass back to unsubscribe().

    pattern supports three forms:
      "decision.proposed"  — exact match
      "decision.*"         — prefix match (any sub-type under that domain)
      "*"                  — all events
    """

    id: UUID
    pattern: str
    handler: Handler


class Bus(ABC):
    @abstractmethod
    async def publish(self, envelope: EventEnvelope) -> None:
        """
        Persist the event durably, then fan out to all matching subscribers.
        Raises if persistence fails; handler failures are isolated and logged.
        """

    @abstractmethod
    async def subscribe(self, pattern: str, handler: Handler) -> Subscription:
        """Register handler for events matching pattern. Returns a Subscription."""

    @abstractmethod
    async def unsubscribe(self, sub: Subscription) -> None:
        """De-register a handler. Safe to call with an already-removed sub."""

    @abstractmethod
    async def close(self) -> None:
        """Graceful shutdown — drain in-flight work and release resources."""
