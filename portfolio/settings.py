from __future__ import annotations

from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PortfolioSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PORTFOLIO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    initial_cash: Decimal = Decimal("10000.00")
    slippage_pct: float = 0.001   # 0.1% market-order slippage
    fee_pct: float = 0.001        # 0.1% per fill

    # ASSISTED-mode parked decisions expire this many seconds after approval.
    # On expiry an audited decision.expired event is emitted and the decision
    # can no longer be executed (it would be re-validated against stale state).
    pending_ttl_seconds: int = 3600   # 1 hour
