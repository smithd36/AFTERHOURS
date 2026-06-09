from pydantic_settings import BaseSettings, SettingsConfigDict


class AlertSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ALERT_")

    price_move_pct_threshold: float = 3.0   # % move to trigger a pct_move alert
    price_move_window_minutes: int = 5       # rolling window for % move calculation
    alert_cooldown_minutes: int = 10         # min gap between repeat alerts of same type
