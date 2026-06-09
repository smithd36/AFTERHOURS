from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CoinbaseFeedSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    ws_url: str = Field(
        default="wss://advanced-trade-ws.coinbase.com",
        alias="COINBASE_WS_URL",
    )
    # Env var format: COINBASE_PRODUCTS=["BTC-USD","ETH-USD"]  (JSON array)
    products: list[str] = Field(
        default=["BTC-USD", "ETH-USD"],
        alias="COINBASE_PRODUCTS",
    )
