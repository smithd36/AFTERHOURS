"""
Price alert generator.

Subscribes to market.tick and publishes signal.created for three conditions:
  24h_high_cross  — price breaks above the rolling 24h high
  24h_low_cross   — price breaks below the rolling 24h low
  pct_move        — price moves ≥ threshold % within the configured window

A per-(instrument, alert_type) cooldown prevents spam on sustained moves.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog

from core.bus.base import Bus, Subscription
from core.schemas.common import Provenance
from core.schemas.events import EventEnvelope, EventType
from core.schemas.signal import Signal, SignalType

from .settings import AlertSettings

# Imported lazily to avoid a circular dep at module level; type-check only.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from watchlist.manager import WatchlistManager

logger = structlog.get_logger(__name__)

# Minimum fraction of the window that must be covered before a pct_move fires.
# Guards against false positives on startup when the window is only a few ticks old.
_MIN_WINDOW_FILL = 0.8


class PriceAlertGenerator:
    """Watches market.tick events and emits signal.created on price conditions."""

    def __init__(
        self,
        bus: Bus,
        settings: AlertSettings | None = None,
        watchlist: WatchlistManager | None = None,
    ) -> None:
        self._bus = bus
        self._settings = settings or AlertSettings()
        self._watchlist = watchlist
        self._sub: Subscription | None = None

        self._last_price: dict[str, Decimal] = {}
        self._windows: dict[str, deque[tuple[datetime, Decimal]]] = {}
        self._cooldowns: dict[tuple[str, str], datetime] = {}

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(EventType.MARKET_TICK, self._handle_tick)
        logger.info("price_alert_generator.started")

    async def stop(self) -> None:
        if self._sub is not None:
            await self._bus.unsubscribe(self._sub)
            self._sub = None
        logger.info("price_alert_generator.stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _handle_tick(self, envelope: EventEnvelope) -> None:
        p: dict[str, Any] = envelope.payload
        instrument: str = p.get("instrument", "")
        price_str: str = p.get("price", "")
        if not instrument or not price_str:
            return
        if self._watchlist is not None and instrument not in self._watchlist.active_instruments:
            return

        price = Decimal(price_str)
        event_time = envelope.event_time
        prev = self._last_price.get(instrument)

        pending: list[tuple[str, str, dict[str, object]]] = []

        # --- 24h boundary crossings ---
        high_str: str = p.get("high_24h", "")
        if high_str and prev is not None:
            high = Decimal(high_str)
            if prev < high <= price:
                pending.append((
                    "24h_high_cross",
                    f"{instrument} broke above 24h high {high_str}",
                    {"alert_type": "24h_high_cross", "price": price_str, "level": high_str},
                ))

        low_str: str = p.get("low_24h", "")
        if low_str and prev is not None:
            low = Decimal(low_str)
            if prev > low >= price:
                pending.append((
                    "24h_low_cross",
                    f"{instrument} broke below 24h low {low_str}",
                    {"alert_type": "24h_low_cross", "price": price_str, "level": low_str},
                ))

        # --- Rolling % move ---
        window = self._windows.setdefault(instrument, deque())
        window.append((event_time, price))
        cutoff = event_time - timedelta(minutes=self._settings.price_move_window_minutes)
        while window and window[0][0] < cutoff:
            window.popleft()

        if len(window) >= 2:
            oldest_ts, oldest_price = window[0]
            window_age = (event_time - oldest_ts).total_seconds()
            required_age = self._settings.price_move_window_minutes * 60 * _MIN_WINDOW_FILL
            if window_age >= required_age and oldest_price > 0:
                pct = abs((price - oldest_price) / oldest_price * 100)
                if pct >= Decimal(str(self._settings.price_move_pct_threshold)):
                    direction = "up" if price > oldest_price else "down"
                    pending.append((
                        "pct_move",
                        f"{instrument} {direction} {float(pct):.1f}% in "
                        f"{self._settings.price_move_window_minutes}m",
                        {
                            "alert_type": "pct_move",
                            "direction": direction,
                            "pct": str(pct.quantize(Decimal("0.01"))),
                            "price": price_str,
                            "window_minutes": self._settings.price_move_window_minutes,
                        },
                    ))

        self._last_price[instrument] = price

        for alert_type, summary, extra in pending:
            if self._cooldown_ok(instrument, alert_type, event_time):
                await self._emit(instrument, alert_type, summary, extra, event_time)

    def _cooldown_ok(self, instrument: str, alert_type: str, now: datetime) -> bool:
        key = (instrument, alert_type)
        last = self._cooldowns.get(key)
        if last is None or (now - last) >= timedelta(minutes=self._settings.alert_cooldown_minutes):
            self._cooldowns[key] = now
            return True
        return False

    async def _emit(
        self,
        instrument: str,
        alert_type: str,
        summary: str,
        extra: dict[str, object],
        event_time: datetime,
    ) -> None:
        now = datetime.now(UTC)
        signal = Signal(
            type=SignalType.PRICE_ALERT,
            instruments=[instrument],
            provenance=Provenance(
                source="price_alert_generator",
                source_id=f"{instrument}:{alert_type}:{event_time.isoformat()}",
                event_time=event_time,
                ingest_time=now,
                url=None,
            ),
            payload={"summary": summary, **extra},
        )
        await self._bus.publish(EventEnvelope(
            event_type=EventType.SIGNAL_CREATED,
            source="price_alert_generator",
            event_time=event_time,
            ingest_time=now,
            payload=signal.model_dump(mode="json"),
        ))
        logger.info("price_alert.fired", instrument=instrument, alert_type=alert_type)
