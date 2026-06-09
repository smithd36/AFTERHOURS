"""
Generic OpenAI-compatible provider.

Works with any service that exposes an OpenAI-compatible chat completions API:
Groq, Mistral, OpenRouter, Together AI, and many others.
"""

from __future__ import annotations

import openai

from ..base import LLMProvider, Message


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float) -> None:
        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._temperature = temperature

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=self._temperature,
            messages=messages,  # type: ignore[arg-type]
        )
        return response.choices[0].message.content or ""
