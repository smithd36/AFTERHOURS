"""LLM record/replay cache tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from reasoning.llm.base import LLMProvider, Message
from reasoning.llm.cache import CachingProvider, JsonFileLLMCache, LLMCacheMiss, prompt_key

MESSAGES: list[Message] = [
    {"role": "system", "content": "You are a trading analyst."},
    {"role": "user", "content": "Form a thesis for BTC-USD."},
]


class CountingProvider(LLMProvider):
    def __init__(self, response: str = "the response") -> None:
        self.response = response
        self.calls = 0

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        self.calls += 1
        return self.response


def test_prompt_key_is_stable_and_content_sensitive() -> None:
    assert prompt_key(MESSAGES) == prompt_key(list(MESSAGES))
    other: list[Message] = [{"role": "user", "content": "different"}]
    assert prompt_key(MESSAGES) != prompt_key(other)


def test_cache_roundtrip_survives_reload(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    cache = JsonFileLLMCache(path)
    assert cache.get("k") is None
    cache.put("k", "v")
    assert cache.get("k") == "v"

    reloaded = JsonFileLLMCache(path)
    assert reloaded.get("k") == "v"
    assert len(reloaded) == 1


async def test_record_mode_calls_inner_once(tmp_path: Path) -> None:
    inner = CountingProvider()
    provider = CachingProvider(JsonFileLLMCache(tmp_path / "c.json"), inner=inner)

    first = await provider.complete(MESSAGES)
    second = await provider.complete(MESSAGES)

    assert first == second == "the response"
    assert inner.calls == 1  # second call served from cache
    assert provider.hits == 1 and provider.misses == 1


async def test_replay_mode_serves_recorded(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    recorder = CachingProvider(JsonFileLLMCache(path), inner=CountingProvider("recorded"))
    await recorder.complete(MESSAGES)

    replayer = CachingProvider(JsonFileLLMCache(path), inner=None)
    assert await replayer.complete(MESSAGES) == "recorded"


async def test_replay_mode_raises_on_miss(tmp_path: Path) -> None:
    provider = CachingProvider(JsonFileLLMCache(tmp_path / "c.json"), inner=None)
    with pytest.raises(LLMCacheMiss):
        await provider.complete(MESSAGES)
