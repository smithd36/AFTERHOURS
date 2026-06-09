from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KrakenFeedSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    ws_url: str = Field(
        default="wss://ws.kraken.com/v2",
        alias="KRAKEN_WS_URL",
    )
    # Canonical format: KRAKEN_PRODUCTS=["BTC-USD","ETH-USD"]
    # Converted to Kraken format (BTC/USD) internally before subscribing.
    products: list[str] = Field(
        default=["BTC-USD", "ETH-USD"],
        alias="KRAKEN_PRODUCTS",
    )
