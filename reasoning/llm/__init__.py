from __future__ import annotations

from .base import LLMProvider, Message
from .cache import CachingProvider, JsonFileLLMCache, LLMCacheMiss
from .settings import PROVIDER_BASE_URLS, PROVIDER_DEFAULT_MODELS, LLMSettings
from .throttle import ThrottledProvider

_REQUIRED_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# Free OpenAI-compatible providers with tight per-minute limits — throttled by
# default (LLM_MAX_RPM=-1 auto). Paid/local providers default to no throttle.
_FREE_OPENAI_COMPATIBLE: frozenset[str] = frozenset({"groq", "mistral", "openrouter"})


def _effective_rpm(s: LLMSettings) -> int:
    if s.max_rpm < 0:
        return 25 if s.provider in _FREE_OPENAI_COMPATIBLE else 0
    return s.max_rpm


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

            base: LLMProvider = AnthropicProvider(
                api_key=s.anthropic_api_key, model=model, temperature=s.temperature
            )
        case "openai":
            from .providers.openai import OpenAIProvider

            base = OpenAIProvider(api_key=s.openai_api_key, model=model, temperature=s.temperature)
        case "ollama":
            from .providers.ollama import OllamaProvider

            base = OllamaProvider(
                base_url=s.ollama_base_url, model=model, temperature=s.temperature
            )
        case "groq" | "mistral" | "openrouter":
            from .providers.openai_compatible import OpenAICompatibleProvider

            key_map = {
                "groq": s.groq_api_key,
                "mistral": s.mistral_api_key,
                "openrouter": s.openrouter_api_key,
            }
            base = OpenAICompatibleProvider(
                base_url=PROVIDER_BASE_URLS[s.provider],
                api_key=key_map[s.provider],
                model=model,
                temperature=s.temperature,
                max_retries=s.max_retries,
                json_mode=s.json_mode,
            )
        case _:
            raise ValueError(f"Unknown LLM provider: {s.provider!r}")

    # Wrap with the rate-limiter/concurrency cap when throttling is active.
    # ThrottledProvider sits inside CachingProvider (app.py), so cache hits never
    # consume a permit. Tune via LLM_MAX_RPM / LLM_MAX_CONCURRENCY.
    rpm = _effective_rpm(s)
    if rpm > 0:
        return ThrottledProvider(base, max_rpm=rpm, max_concurrency=s.max_concurrency)
    return base


__all__ = [
    "CachingProvider",
    "JsonFileLLMCache",
    "LLMCacheMiss",
    "LLMProvider",
    "LLMSettings",
    "Message",
    "ThrottledProvider",
    "create_provider",
]
