from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ThesisSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="THESIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    min_signals_to_trigger: int = 3
    signal_window_minutes: int = 15
    cooldown_minutes: int = 60
    max_signals_per_prompt: int = 10
    expiry_hours: int = 8
    max_tokens: int = 1024
