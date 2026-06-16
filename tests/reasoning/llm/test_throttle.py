"""Tests for the LLM rate-limit / concurrency wrapper and Retry-After backoff."""

from __future__ import annotations

import asyncio
from time import monotonic

from reasoning.llm.base import LLMProvider, Message
from reasoning.llm.providers.openai_compatible import _retry_after_seconds
from reasoning.llm.throttle import ThrottledProvider, _TokenBucket


class _FakeProvider(LLMProvider):
    """Records call count and the peak number of concurrent in-flight calls."""

    def __init__(self, delay: float = 0.0) -> None:
        self._delay = delay
        self.calls = 0
        self._in_flight = 0
        self.peak_in_flight = 0

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        self.calls += 1
        self._in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        if self._delay:
            await asyncio.sleep(self._delay)
        self._in_flight -= 1
        return "ok"


_MSG: list[Message] = [{"role": "user", "content": "hi"}]


# ---------------------------------------------------------------------------
# _TokenBucket
# ---------------------------------------------------------------------------


async def test_token_bucket_allows_initial_burst_then_paces() -> None:
    # rate=4 over 0.2s → 20 permits/sec. First 4 are instant; the next 2 each
    # cost ~0.05s, so 6 total should take noticeably longer than the first 4.
    bucket = _TokenBucket(rate=4, per=0.2)

    start = monotonic()
    for _ in range(4):
        await bucket.acquire()
    burst_elapsed = monotonic() - start
    assert burst_elapsed < 0.05  # the initial allowance is free

    start = monotonic()
    for _ in range(2):
        await bucket.acquire()
    paced_elapsed = monotonic() - start
    assert paced_elapsed >= 0.07  # ~0.05s/permit once the bucket is drained


# ---------------------------------------------------------------------------
# ThrottledProvider
# ---------------------------------------------------------------------------


async def test_concurrency_cap_limits_in_flight() -> None:
    fake = _FakeProvider(delay=0.03)
    throttled = ThrottledProvider(fake, max_rpm=0, max_concurrency=2)

    await asyncio.gather(*(throttled.complete(_MSG) for _ in range(8)))

    assert fake.calls == 8
    assert fake.peak_in_flight == 2  # never more than the cap


async def test_no_throttle_passthrough() -> None:
    fake = _FakeProvider()
    throttled = ThrottledProvider(fake, max_rpm=0, max_concurrency=0)
    assert await throttled.complete(_MSG) == "ok"
    assert fake.calls == 1


async def test_rate_limit_paces_requests() -> None:
    fake = _FakeProvider()
    throttled = ThrottledProvider(fake, max_rpm=4, max_concurrency=0)
    # The production window is 60s; swap in a fast one so pacing is observable.
    # Bucket starts full (4 free), so calls 5-6 are paced at ~0.05s each.
    throttled._bucket = _TokenBucket(rate=4, per=0.2)
    start = monotonic()
    await asyncio.gather(*(throttled.complete(_MSG) for _ in range(6)))
    assert monotonic() - start >= 0.07
    assert fake.calls == 6


# ---------------------------------------------------------------------------
# _retry_after_seconds
# ---------------------------------------------------------------------------


def test_retry_after_honors_header() -> None:
    wait = _retry_after_seconds({"retry-after": "5"}, attempt=1)
    assert 5.0 <= wait <= 5.5


def test_retry_after_caps_header() -> None:
    wait = _retry_after_seconds({"retry-after": "9999"}, attempt=1, cap=30.0)
    assert wait <= 30.5


def test_retry_after_falls_back_to_backoff() -> None:
    # No header → exponential backoff grows with attempt number.
    w1 = _retry_after_seconds({}, attempt=1)
    w3 = _retry_after_seconds({}, attempt=3)
    assert w1 < w3
    assert w3 <= 30.5  # capped


def test_retry_after_ignores_garbage_header() -> None:
    # Non-numeric Retry-After falls back to backoff rather than raising.
    wait = _retry_after_seconds({"retry-after": "soon"}, attempt=1)
    assert wait > 0
