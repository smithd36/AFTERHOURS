from __future__ import annotations

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class InsiderFeedSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INSIDER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # EDGAR "latest filings" Atom feed, scoped to Form 4. count is the rolling
    # window size; during the post-close filing surge some Form 4s scroll off
    # between polls — acceptable for enrich-only (ADR-010). Per-CIK polling of
    # watched names is the upgrade if completeness ever matters.
    current_url: str = (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        "?action=getcurrent&type=4&owner=include&count=100&output=atom"
    )
    poll_interval_seconds: int = 300  # 5 minutes

    # Materiality floor: only open-market buys/sells worth at least this much
    # (USD) become signals. Below it is noise to the reasoning layer.
    min_transaction_usd: Decimal = Decimal("100000")

    # SEC fair-access policy requires a descriptive User-Agent with contact info;
    # a generic UA gets a 403. Set INSIDER_USER_AGENT in .env to your contact.
    user_agent: str = "AFTERHOURS research bot (set INSIDER_USER_AGENT to your contact email)"
