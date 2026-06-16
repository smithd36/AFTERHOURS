"""
Outbound rate limiting for LLM providers.

`ThrottledProvider` wraps any `LLMProvider` with a requests-per-minute token
bucket and a concurrency cap, so a burst of signals (many instruments firing
theses/decisions at once, across instances sharing one provider account) gets
*queued* instead of slamming the provider's per-minute ceiling — the cause of
free-tier 429 storms even when daily volume is tiny.

It is provider-agnostic and sits *inside* `CachingProvider`, so cache hits
never wait on a permit (see the wiring in `gateway/app.py`).
"""

from __future__ import annotations

import asyncio
from time import monotonic

import structlog

from .base import LLMProvider, Message

logger = structlog.get_logger(__name__)


class _TokenBucket:
    """Async token bucket: `rate` permits, refilled continuously over `per` seconds.

    Acquisition is serialized through a lock so callers are paced in arrival
    order; a caller that finds the bucket empty sleeps exactly long enough for
    one permit to accrue, then re-checks.
    """

    def __init__(self, rate: int, per: float = 60.0) -> None:
        self._rate = float(rate)
        self._per = per
        self._allowance = float(rate)
        self._last = monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = monotonic()
                self._allowance = min(
                    self._rate,
                    self._allowance + (now - self._last) * (self._rate / self._per),
                )
                self._last = now
                if self._allowance >= 1.0:
                    self._allowance -= 1.0
                    return
                await asyncio.sleep((1.0 - self._allowance) * (self._per / self._rate))


class ThrottledProvider(LLMProvider):
    """Rate-limit + concurrency-cap wrapper around any `LLMProvider`."""

    def __init__(self, inner: LLMProvider, *, max_rpm: int, max_concurrency: int = 0) -> None:
        self.inner = inner
        self._bucket = _TokenBucket(max_rpm) if max_rpm > 0 else None
        self._sem = asyncio.Semaphore(max_concurrency) if max_concurrency > 0 else None
        logger.info("llm_throttle.enabled", max_rpm=max_rpm, max_concurrency=max_concurrency)

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        if self._bucket is not None:
            await self._bucket.acquire()
        if self._sem is not None:
            async with self._sem:
                return await self.inner.complete(messages, max_tokens=max_tokens)
        return await self.inner.complete(messages, max_tokens=max_tokens)
