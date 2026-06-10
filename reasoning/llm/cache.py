"""
LLM record/replay cache.

`CachingProvider` wraps any `LLMProvider` and keys responses by a sha256
of the full message list — the same content the Decision's `prompt_hash`
is derived from. Two uses:

  Record (live gateway, backtest --llm live):
      CachingProvider(cache, inner=real_provider)
      → cache miss calls the inner provider and records the response.

  Replay (backtest --llm replay, the deterministic default):
      CachingProvider(cache, inner=None)
      → cache miss raises LLMCacheMiss; the bus isolates the handler
        error, so the affected thesis/decision is skipped and logged.

The cache is a JSON file *separate from the event DB* on purpose: the dev
database is disposable (deleted to reset), but recorded LLM responses are
what make backtests reproducible and free — they must outlive DB resets.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import structlog

from .base import LLMProvider, Message

logger = structlog.get_logger(__name__)


class LLMCacheMiss(Exception):
    """Raised in replay mode when no recorded response exists for a prompt."""


def prompt_key(messages: list[Message]) -> str:
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()


class JsonFileLLMCache:
    """Durable prompt-hash → response store. Loads lazily, writes atomically."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._data: dict[str, dict[str, str]] = {}
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("llm_cache.unreadable", path=str(self._path))

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str) -> str | None:
        entry = self._data.get(key)
        return entry["response"] if entry else None

    def put(self, key: str, response: str) -> None:
        self._data[key] = {
            "response": response,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        os.replace(tmp, self._path)


class CachingProvider(LLMProvider):
    def __init__(self, cache: JsonFileLLMCache, inner: LLMProvider | None = None) -> None:
        self._cache = cache
        self._inner = inner
        self.hits = 0
        self.misses = 0

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        key = prompt_key(messages)
        cached = self._cache.get(key)
        if cached is not None:
            self.hits += 1
            return cached

        self.misses += 1
        if self._inner is None:
            raise LLMCacheMiss(f"no recorded response for prompt {key[:12]}… (replay mode)")

        response = await self._inner.complete(messages, max_tokens=max_tokens)
        self._cache.put(key, response)
        return response
