from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal, TypedDict


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        """Send messages and return the assistant's text response."""
