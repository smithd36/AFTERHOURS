from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class DecisionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DECISION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    max_tokens: int = 1024
    # Cooldown prevents generating multiple decisions for the same thesis.
    # The generator tracks processed thesis IDs so each thesis yields at most one decision.
