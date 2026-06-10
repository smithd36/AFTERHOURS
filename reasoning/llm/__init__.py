from __future__ import annotations

from .base import LLMProvider, Message
from .cache import CachingProvider, JsonFileLLMCache, LLMCacheMiss
from .settings import LLMSettings, PROVIDER_BASE_URLS, PROVIDER_DEFAULT_MODELS

_REQUIRED_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _resolve_key(s: LLMSettings) -> str:
    return {
        "anthropic": s.anthropic_api_key,
        "openai": s.openai_api_key,
        "groq": s.groq_api_key,
        "mistral": s.mistral_api_key,
        "openrouter": s.openrouter_api_key,
    }.get(s.provider, "")


def create_provider(settings: LLMSettings | None = None) -> LLMProvider:
    s = settings or LLMSettings()

    env_var = _REQUIRED_KEYS.get(s.provider)
    if env_var and not _resolve_key(s):
        raise ValueError(
            f"LLM provider '{s.provider}' requires {env_var} to be set in your .env file."
        )

    model = s.model or PROVIDER_DEFAULT_MODELS.get(s.provider, "")

    match s.provider:
        case "anthropic":
            from .providers.anthropic import AnthropicProvider
            return AnthropicProvider(api_key=s.anthropic_api_key, model=model, temperature=s.temperature)
        case "openai":
            from .providers.openai import OpenAIProvider
            return OpenAIProvider(api_key=s.openai_api_key, model=model, temperature=s.temperature)
        case "ollama":
            from .providers.ollama import OllamaProvider
            return OllamaProvider(base_url=s.ollama_base_url, model=model, temperature=s.temperature)
        case "groq" | "mistral" | "openrouter":
            from .providers.openai_compatible import OpenAICompatibleProvider
            key_map = {
                "groq": s.groq_api_key,
                "mistral": s.mistral_api_key,
                "openrouter": s.openrouter_api_key,
            }
            return OpenAICompatibleProvider(
                base_url=PROVIDER_BASE_URLS[s.provider],
                api_key=key_map[s.provider],
                model=model,
                temperature=s.temperature,
            )
        case _:
            raise ValueError(f"Unknown LLM provider: {s.provider!r}")


__all__ = [
    "CachingProvider",
    "JsonFileLLMCache",
    "LLMCacheMiss",
    "LLMProvider",
    "LLMSettings",
    "Message",
    "create_provider",
]
