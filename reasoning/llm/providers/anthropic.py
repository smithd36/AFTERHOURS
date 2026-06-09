from __future__ import annotations

import anthropic

from ..base import LLMProvider, Message


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, temperature: float) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._temperature = temperature

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        non_system = [m for m in messages if m["role"] != "system"]
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=self._temperature,
            system=system,
            messages=non_system,  # type: ignore[arg-type]
        )
        block = response.content[0]
        return block.text if hasattr(block, "text") else ""
