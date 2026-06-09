from pydantic_settings import BaseSettings, SettingsConfigDict


class NewsFeedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEWS_")

    feed_urls: list[str] = [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
    ]
    poll_interval_seconds: int = 300  # 5 minutes
