from __future__ import annotations

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class SupplyChainSettings(BaseSettings):
    """Supply-chain / quiet-partner dependencies from 10-K filings.

    PUBLIC FILINGS ONLY (ADR-010): extracts customer-concentration disclosures
    ("Customer X accounted for N% of revenue") from each watched equity's latest
    10-K. Coarse by design — a free, public-record proxy for the paid relationship
    graphs (FactSet/Bloomberg SPLC). Expert-network / channel-check sourcing is an
    explicit MNPI stop and is out of scope.

    Per watched equity (name/CIK-keyed), like the gov-exposure feed; inert on a
    crypto-only watchlist. Free, no API key (SEC EDGAR).
    """

    model_config = SettingsConfigDict(
        env_prefix="SUPPLYCHAIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    sec_tickers_url: str = "https://www.sec.gov/files/company_tickers.json"
    submissions_url: str = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
    # SEC requires a descriptive User-Agent; a generic one gets a 403.
    user_agent: str = "AFTERHOURS research bot (set SUPPLYCHAIN_USER_AGENT to your contact email)"

    poll_interval_seconds: int = 604_800  # weekly — 10-Ks are annual
    lookback_days: int = 400  # only emit a 10-K filed within ~13 months (the latest annual)
    min_revenue_pct: Decimal = Decimal("10")  # Reg S-K customer-concentration threshold
