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
    # Per-client outbound WebSocket buffer. Each connected browser gets its own
    # bounded queue drained by a dedicated writer task; when a client can't keep
    # up its queue fills and the *oldest* messages are dropped for that client
    # only — a slow socket never back-pressures the event bus (and thus the
    # Kraken dispatch loop / risk engine tick path). Sized for a burst of ticks;
    # a client that falls this far behind is already showing stale data.
    ws_client_queue_size: int = Field(default=512, alias="WS_CLIENT_QUEUE_SIZE")
