from __future__ import annotations

import httpx
import structlog

from ..base import LLMProvider, Message

logger = structlog.get_logger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model: str, temperature: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self._temperature, "num_predict": max_tokens},
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            data: dict[str, object] = response.json()
            msg = data.get("message", {})
            return str(msg.get("content", "")) if isinstance(msg, dict) else ""  # type: ignore[union-attr]
