from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CalibrationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CALIBRATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Outcome resolution: TimeHorizon → wall duration ---
    # Invented defaults (docs/phase4-plan.md) — tune as resolutions accumulate.
    horizon_scalp_minutes: int = 30
    horizon_intraday_hours: int = 4
    horizon_swing_days: int = 3
    horizon_position_days: int = 21

    # --- ECE measurement ---
    ece_buckets: int = 10

    # --- Autonomy graduation gates (PLANNING Appendix B, Balanced profile) ---
    gate_observe_min_sample: int = 50  # resolved shadow decisions for Observe → Paper
    gate_observe_max_ece: float = 0.18
    gate_paper_min_sample: int = 100  # resolved paper decisions for Paper → Assisted
    gate_paper_min_days: int = 14  # minimum span of the paper sample
    gate_paper_max_ece: float = 0.12

    # --- Economic readiness (Paper → Assisted): cost-adjusted round-trip P&L ---
    # Calibration proves confidence matches outcomes; it says nothing about money.
    # These gate on realized P&L net of fees (Portfolio.realized_trades) so a
    # well-calibrated but unprofitable strategy cannot graduate.
    gate_econ_min_trades: int = 50  # closed round-trips before economics are trusted
    gate_econ_min_profit_factor: float = 1.1  # gross win / gross loss
    gate_econ_max_drawdown_pct: float = 0.20  # max peak-to-trough, as fraction of initial cash
