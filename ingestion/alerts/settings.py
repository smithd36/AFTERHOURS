from pydantic_settings import BaseSettings, SettingsConfigDict


class AlertSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALERT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 0.5% in 15 minutes is a notable-but-regular move for BTC/ETH — fires a
    # few times a day. The old default (3% in 5 min) is a flash-crash filter
    # that fired roughly never; raise the threshold via ALERT_* env vars if
    # the feed gets noisy.
    price_move_pct_threshold: float = 0.5   # % move to trigger a pct_move alert
    price_move_window_minutes: int = 15      # rolling window for % move calculation
    alert_cooldown_minutes: int = 10         # min gap between repeat alerts of same type
