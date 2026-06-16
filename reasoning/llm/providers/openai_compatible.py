"""
Generic OpenAI-compatible provider.

Works with any service that exposes an OpenAI-compatible chat completions API:
Groq, Mistral, OpenRouter, Together AI, and many others.

Two robustness features beyond a bare call:
  - Retry-After-aware backoff on 429 / transient 5xx. The SDK's own retries are
    disabled (max_retries=0) so we own the loop and can log *which* rate-limit
    bucket was hit (requests-per-minute vs tokens-per-minute) from the response
    headers — the detail you need to diagnose free-tier 429s.
  - Optional JSON mode (response_format=json_object), which makes the model emit
    valid JSON on the first try and cuts the generators' parse-retry round-trips.
    Disable (LLM_JSON_MODE=false) for models that reject response_format.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Mapping
from typing import Any

import openai
import structlog

from ..base import LLMProvider, Message

logger = structlog.get_logger(__name__)

# Transient errors worth retrying with plain exponential backoff (429 is handled
# separately so we can honor Retry-After and log the rate-limit headers).
_TRANSIENT = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


def _retry_after_seconds(
    headers: Mapping[str, str], attempt: int, *, base: float = 1.0, cap: float = 30.0
) -> float:
    """Honor a Retry-After header when present; otherwise exponential backoff + jitter."""
    raw = headers.get("retry-after") if headers else None
    if raw:
        try:
            return float(min(float(raw), cap) + random.uniform(0, 0.25))
        except ValueError:
            pass
    return float(min(base * (2 ** (attempt - 1)), cap) + random.uniform(0, 0.5))


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float,
        *,
        max_retries: int = 6,
        json_mode: bool = True,
    ) -> None:
        # max_retries=0: we own the retry loop (see complete) so we can read the
        # rate-limit headers off each 429 instead of the SDK swallowing them.
        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0)
        self._model = model
        self._temperature = temperature
        self._max_retries = max_retries
        self._json_mode = json_mode

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": self._temperature,
            "messages": messages,
        }
        if self._json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        attempt = 0
        while True:
            try:
                response = await self._client.chat.completions.create(**kwargs)
                return response.choices[0].message.content or ""
            except openai.RateLimitError as exc:
                attempt += 1
                headers = getattr(exc.response, "headers", {}) or {}
                wait = _retry_after_seconds(headers, attempt)
                logger.warning(
                    "llm.rate_limited",
                    model=self._model,
                    attempt=attempt,
                    retry_in_s=round(wait, 2),
                    limit_requests=headers.get("x-ratelimit-limit-requests"),
                    remaining_requests=headers.get("x-ratelimit-remaining-requests"),
                    limit_tokens=headers.get("x-ratelimit-limit-tokens"),
                    remaining_tokens=headers.get("x-ratelimit-remaining-tokens"),
                    retry_after=headers.get("retry-after"),
                )
                if attempt > self._max_retries:
                    raise
                await asyncio.sleep(wait)
            except _TRANSIENT as exc:
                attempt += 1
                if attempt > self._max_retries:
                    raise
                wait = min(2 ** (attempt - 1), 30.0) + random.uniform(0, 0.5)
                logger.warning(
                    "llm.transient_error",
                    model=self._model,
                    attempt=attempt,
                    error=type(exc).__name__,
                    retry_in_s=round(wait, 2),
                )
                await asyncio.sleep(wait)
