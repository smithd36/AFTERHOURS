from __future__ import annotations

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class GovExposureSettings(BaseSettings):
    """Lobbying (Senate LDA) + government contracts (USASpending), bundled.

    Both APIs are name-keyed (no ticker), so this feed resolves ticker → company
    name via SEC's free company_tickers.json and queries per watched equity —
    enrich-only by construction (no market-wide firehose, so no Phase 6B
    discovery substrate; insider/congress are the discovery drivers). Both data
    sources are free; USASpending needs no key, the LDA key is optional and only
    raises the anonymous rate limit.
    """

    model_config = SettingsConfigDict(
        env_prefix="GOVEXP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    lda_url: str = "https://lda.senate.gov/api/v1/filings/"
    lda_api_key: str = ""  # optional free key (lda.senate.gov); raises rate limit
    usaspending_url: str = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    sec_tickers_url: str = "https://www.sec.gov/files/company_tickers.json"
    # SEC requires a descriptive User-Agent (used only for the ticker→name map).
    user_agent: str = "AFTERHOURS research bot (set GOVEXP_USER_AGENT to your contact email)"

    # Lobbying/contracts are low frequency — poll every 6h.
    poll_interval_seconds: int = 21_600
    # Only emit filings/awards disclosed within this window (bounds cold-start volume).
    lookback_days: int = 30

    min_lobbying_usd: Decimal = Decimal("50000")
    min_contract_usd: Decimal = Decimal("1000000")
