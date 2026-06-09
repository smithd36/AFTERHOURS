"""Abstract Feed interface. Every exchange/data-source adapter implements this."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Feed(ABC):
    @abstractmethod
    async def run(self) -> None:
        """
        Run the feed until cancelled. Implementations must reconnect
        automatically on disconnection; only asyncio.CancelledError stops it.
        """

    @abstractmethod
    async def close(self) -> None:
        """Signal a graceful stop. Callers can also cancel the task directly."""
