from __future__ import annotations

from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RiskSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RISK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Sizing
    max_position_pct: float = 0.05       # max 5% of portfolio per position
    max_trade_loss_pct: float = 0.02     # risk 2% of portfolio per trade
    stop_loss_pct: float = 0.03          # 3% price move triggers stop

    # Limits
    max_open_positions: int = 5
    max_daily_loss_pct: float = 0.05     # 5% daily loss → auto-halt
