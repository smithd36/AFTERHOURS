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

    # Affordability (PLANNING §2.4 — "can we afford it" is a required pre-trade
    # check). max_position_pct sizes against total_value (cash + marked
    # positions), which after drawdowns can exceed available cash; these bound
    # the trade to cash we actually hold.
    cash_buffer_pct: float = 0.01        # keep 1% of cash unspent (fee/slippage headroom)
    min_trade_size_usd: Decimal = Decimal("10.00")   # reject trades smaller than this

    # Limits
    max_open_positions: int = 5
    max_daily_loss_pct: float = 0.05     # 5% daily loss → auto-halt

    # Equity trading is session-aware: reject an entry whose venue is closed
    # (NYSE regular hours) rather than opening at a stale off-hours mark. Crypto
    # is unaffected (24/7). See docs/pre-phase-7-risk-review.md section 12.
    equity_session_gating: bool = True
