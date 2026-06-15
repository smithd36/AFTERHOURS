from __future__ import annotations

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class CongressFeedSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QUIVER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Free-tier token from quiverquant.com. Empty → the feed no-ops (subscriptions
    # tracked, nothing emitted), mirroring EquityFeed, so it is safe to wire in
    # unconditionally and costs nothing until a token is provided.
    api_token: str = ""
    base_url: str = "https://api.quiverquant.com/beta/live/congresstrading"

    # Congressional disclosures are a daily batch with a 30–45 day legal reporting
    # lag, so polling hourly is generous. (event_time is the disclosure date, not
    # the transaction date — the data is stale-by-design; see normalizer.)
    poll_interval_seconds: int = 3600

    # Materiality floor against the LOWER bound of the disclosed dollar range
    # (filings report buckets like "$1,001 - $15,000"); below it is noise.
    min_amount_usd: Decimal = Decimal("50000")
