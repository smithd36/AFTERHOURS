from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EquityFeedSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    provider: str = Field(
        default="alpaca",
        alias="EQUITY_FEED_PROVIDER",
        description="'alpaca' | 'polygon' | 'none'",
    )
    api_key: str = Field(default="", alias="EQUITY_FEED_API_KEY")
    api_secret: str = Field(default="", alias="EQUITY_FEED_API_SECRET")
    poll_interval_seconds: int = Field(
        default=60,
        alias="EQUITY_POLL_INTERVAL_SECONDS",
    )
