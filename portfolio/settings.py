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
