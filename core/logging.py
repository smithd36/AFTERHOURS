"""
Logging configuration for AFTERHOURS.

Call `configure_logging()` once at application startup, before any log
calls are made. After that every module uses the standard pattern:

    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("event.name", key="value", another_key=123)

Log events are named with dot-separated domain.verb keys (same convention
as the event bus) so they sort and filter consistently:
    "bus.event_persisted", "db.migration.applied", "feed.tick_received", …

Context variables — bind once per async task, carried into every log call
made within that task without passing them explicitly:

    structlog.contextvars.bind_contextvars(
        decision_id=str(decision.id),
        instrument="BTC-USD",
    )
    logger.info("decision.approved")   # → includes decision_id + instrument
    structlog.contextvars.clear_contextvars()

Two output formats, controlled by the LOG_FORMAT env var:
    "dev"  — coloured, human-readable (default for local work)
    "json" — one JSON object per line (production / log aggregators)
"""

from __future__ import annotations

import logging
import sys
from typing import Literal

import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class LoggingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: Literal["dev", "json"] = Field(default="dev", alias="LOG_FORMAT")


# ---------------------------------------------------------------------------
# Noisy third-party loggers — capped at WARNING so they don't drown the feed
# ---------------------------------------------------------------------------

_LIBRARY_LOG_LEVELS: dict[str, int] = {
    "uvicorn.access": logging.WARNING,  # per-request lines are too noisy at INFO
    "httpx": logging.WARNING,
    "ccxt": logging.WARNING,
    "websockets": logging.WARNING,
    "asyncio": logging.WARNING,
}

# ---------------------------------------------------------------------------
# Shared processor chain (applied by both structlog and stdlib foreign chain)
# ---------------------------------------------------------------------------

_SHARED_PROCESSORS: list[structlog.types.Processor] = [
    # Merge any context vars bound via bind_contextvars() into this event.
    structlog.contextvars.merge_contextvars,
    # Add logger name (module path) and level to every event.
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    # Format positional args: logger.info("hello %s", name) → "hello world"
    structlog.stdlib.PositionalArgumentsFormatter(),
    # ISO-8601 UTC timestamp on every event.
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    # Include stack_info= keyword if passed.
    structlog.processors.StackInfoRenderer(),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_logging(
    level: str | None = None,
    fmt: Literal["dev", "json"] | None = None,
) -> None:
    """
    Configure structlog + stdlib logging.

    level and fmt override env vars (LOG_LEVEL, LOG_FORMAT) when given.
    Safe to call multiple times — last call wins (useful in tests).
    """
    settings = LoggingSettings()
    log_level_str = (level or settings.log_level).upper()
    log_fmt = fmt or settings.log_format
    log_level = getattr(logging, log_level_str, logging.INFO)

    # Choose exc info and rendering processors based on format.
    if log_fmt == "json":
        # format_exc_info renders the traceback as a plain string in the JSON blob.
        exc_processor: structlog.types.Processor = structlog.processors.format_exc_info
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        # set_exc_info pulls sys.exc_info() when exc_info=True; ConsoleRenderer formats it.
        exc_processor = structlog.dev.set_exc_info
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # --- structlog configuration ---
    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            exc_processor,
            # Package the event dict for ProcessorFormatter (stdlib bridge).
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        # Use stdlib loggers as the underlying transport so all output flows
        # through one handler — structlog events and library events look identical.
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # --- stdlib handler with structlog formatter ---
    formatter = structlog.stdlib.ProcessorFormatter(
        # foreign_pre_chain: applied to log records that arrive via stdlib
        # (uvicorn, httpx, ccxt, …) before the final processors run.
        foreign_pre_chain=[*_SHARED_PROCESSORS, exc_processor],
        # processors: applied last to ALL events (structlog + foreign).
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Cap library loggers — never quieter than the requested level.
    for name, lib_level in _LIBRARY_LOG_LEVELS.items():
        logging.getLogger(name).setLevel(max(lib_level, log_level))
