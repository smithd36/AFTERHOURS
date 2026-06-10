from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WatchlistSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    # Comma-separated list of instruments added to the watchlist on first run
    # if the table is empty.  Canonical format: "BTC-USD,ETH-USD"
    default_instruments: list[str] = Field(
        default=["BTC-USD", "ETH-USD"],
        alias="WATCHLIST_DEFAULT_INSTRUMENTS",
    )
    # Default market type for the seed instruments above ("crypto" or "equity").
    default_market: str = Field(
        default="crypto",
        alias="WATCHLIST_DEFAULT_MARKET",
    )
