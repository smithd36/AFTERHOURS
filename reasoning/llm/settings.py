from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["anthropic", "openai", "ollama", "groq", "mistral", "openrouter"]

# Per-provider model defaults — used when LLM_MODEL is not explicitly set.
PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "ollama": "llama3.2",
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile",
    "mistral": "mistral-small-latest",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
}

# Base URLs for OpenAI-compatible providers
PROVIDER_BASE_URLS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: Provider = "ollama"
    # Empty string → factory fills in the provider-appropriate default from PROVIDER_DEFAULT_MODELS
    model: str = ""
    ollama_base_url: str = "http://localhost:11434"
    max_tokens: int = 1024
    temperature: float = 0.3
    # Record/replay cache — kept outside the (disposable) event DB so recorded
    # responses survive DB resets and power deterministic backtests.
    cache_path: str = "llm_cache.json"

    # Standard env var names — validation_alias bypasses the LLM_ prefix
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    groq_api_key: str = Field(default="", validation_alias="GROQ_API_KEY")
    mistral_api_key: str = Field(default="", validation_alias="MISTRAL_API_KEY")
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
