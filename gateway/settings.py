from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    host: str = Field(default="0.0.0.0", alias="GATEWAY_HOST")
    port: int = Field(default=8000, alias="GATEWAY_PORT")
    # In dev the Vite proxy handles CORS; in prod list real origins here.
    # Format: CORS_ORIGINS=["http://localhost:5173","https://app.example.com"]
    cors_origins: list[str] = Field(
        default=["http://localhost:5173"],
        alias="CORS_ORIGINS",
    )
