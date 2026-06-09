from __future__ import annotations

import openai

from ..base import LLMProvider, Message


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, temperature: float) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key)
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
