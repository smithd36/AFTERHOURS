"""
Tests for PriceAlertGenerator.

Uses a real InProcessBus so the full publish → subscribe → handler path
is exercised. Time is controlled via explicit event_time values on ticks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType
from ingestion.alerts import AlertSettings, PriceAlertGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tick(
    instrument: str,
    price: str,
    *,
    high_24h: str | None = None,
    low_24h: str | None = None,
    event_time: datetime | None = None,
) -> EventEnvelope:
    now = datetime.now(UTC)
    payload: dict[str, str] = {"instrument": instrument, "price": price}
    if high_24h is not None:
        payload["high_24h"] = high_24h
    if low_24h is not None:
        payload["low_24h"] = low_24h
    return EventEnvelope(
        event_type=EventType.MARKET_TICK,
        source="test",
        event_time=event_time or now,
        ingest_time=now,
        payload=payload,
    )


@pytest.fixture
async def bus_and_gen():
    store = InMemoryEventStore()
    bus = InProcessBus(store)
    settings = AlertSettings(
        price_move_pct_threshold=3.0,
        price_move_window_minutes=5,
        alert_cooldown_minutes=10,
    )
    gen = PriceAlertGenerator(bus, settings)
    await gen.start()
    yield bus, gen
    await gen.stop()
    await bus.close()


async def _collect_signals(bus: InProcessBus) -> list[EventEnvelope]:
    received: list[EventEnvelope] = []

    async def handler(env: EventEnvelope) -> None:
        received.append(env)

    sub = await bus.subscribe(EventType.SIGNAL_CREATED, handler)
    return received, sub  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestGeneratorLifecycle:
    async def test_start_subscribes_to_bus(self) -> None:
        store = InMemoryEventStore()
        bus = InProcessBus(store)
        gen = PriceAlertGenerator(bus)
        assert gen._sub is None
        await gen.start()
        assert gen._sub is not None
        await gen.stop()
        await bus.close()

    async def test_stop_clears_subscription(self) -> None:
        store = InMemoryEventStore()
        bus = InProcessBus(store)
        gen = PriceAlertGenerator(bus)
        await gen.start()
        await gen.stop()
        assert gen._sub is None

    async def test_stop_is_idempotent(self, bus_and_gen: tuple) -> None:
        _, gen = bus_and_gen
        await gen.stop()
        await gen.stop()  # must not raise


# ---------------------------------------------------------------------------
# No alert on first tick
# ---------------------------------------------------------------------------


class TestFirstTick:
    async def test_no_alert_on_first_tick(self, bus_and_gen: tuple) -> None:
        bus, _ = bus_and_gen
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe(EventType.SIGNAL_CREATED, handler)
        await bus.publish(_tick("BTC-USD", "65000", high_24h="66000", low_24h="64000"))
        assert received == []


# ---------------------------------------------------------------------------
# 24h high crossing
# ---------------------------------------------------------------------------


class TestHighCross:
    async def test_fires_when_price_crosses_above_high(self, bus_and_gen: tuple) -> None:
        bus, _ = bus_and_gen
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe(EventType.SIGNAL_CREATED, handler)

        # First tick establishes last_price = 64900 (below high 65000)
        await bus.publish(_tick("BTC-USD", "64900", high_24h="65000"))
        assert received == []

        # Second tick: price (65100) crosses above high_24h (65000)
        await bus.publish(_tick("BTC-USD", "65100", high_24h="65000"))
        assert len(received) == 1
        assert received[0].payload["type"] == "price_alert"
        assert received[0].payload["payload"]["alert_type"] == "24h_high_cross"

    async def test_does_not_fire_below_high(self, bus_and_gen: tuple) -> None:
        bus, _ = bus_and_gen
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe(EventType.SIGNAL_CREATED, handler)
        await bus.publish(_tick("BTC-USD", "64000", high_24h="65000"))
        await bus.publish(_tick("BTC-USD", "64500", high_24h="65000"))
        assert received == []

    async def test_respects_cooldown(self, bus_and_gen: tuple) -> None:
        bus, _ = bus_and_gen
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe(EventType.SIGNAL_CREATED, handler)
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

        await bus.publish(_tick("BTC-USD", "64900", high_24h="65000", event_time=t0))
        await bus.publish(_tick("BTC-USD", "65100", high_24h="65000", event_time=t0 + timedelta(seconds=1)))
        # Same crossing again 2 minutes later — within 10m cooldown
        await bus.publish(_tick("BTC-USD", "64950", high_24h="65000", event_time=t0 + timedelta(minutes=2)))
        await bus.publish(_tick("BTC-USD", "65200", high_24h="65000", event_time=t0 + timedelta(minutes=2, seconds=1)))

        assert len(received) == 1  # only the first crossing fires


# ---------------------------------------------------------------------------
# 24h low crossing
# ---------------------------------------------------------------------------


class TestLowCross:
    async def test_fires_when_price_crosses_below_low(self, bus_and_gen: tuple) -> None:
        bus, _ = bus_and_gen
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe(EventType.SIGNAL_CREATED, handler)

        await bus.publish(_tick("BTC-USD", "64100", low_24h="64000"))
        await bus.publish(_tick("BTC-USD", "63900", low_24h="64000"))

        assert len(received) == 1
        assert received[0].payload["payload"]["alert_type"] == "24h_low_cross"


# ---------------------------------------------------------------------------
# Percentage move
# ---------------------------------------------------------------------------


class TestPctMove:
    async def test_fires_on_large_move(self, bus_and_gen: tuple) -> None:
        bus, _ = bus_and_gen
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe(EventType.SIGNAL_CREATED, handler)

        # Use event_times spread across more than 80% of the 5-minute window
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        # Oldest tick: 5 minutes ago (price 60000)
        await bus.publish(_tick("BTC-USD", "60000", event_time=t0))
        # Current tick: 5% move up, 5 minutes later (window fully covered)
        await bus.publish(_tick("BTC-USD", "63000", event_time=t0 + timedelta(minutes=5)))

        pct_alerts = [
            e for e in received if e.payload["payload"].get("alert_type") == "pct_move"
        ]
        assert len(pct_alerts) == 1
        assert pct_alerts[0].payload["payload"]["direction"] == "up"

    async def test_does_not_fire_when_window_too_young(self, bus_and_gen: tuple) -> None:
        bus, _ = bus_and_gen
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe(EventType.SIGNAL_CREATED, handler)

        # Two ticks 10 seconds apart — window is far too young (< 80% of 5 min)
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        await bus.publish(_tick("BTC-USD", "60000", event_time=t0))
        await bus.publish(_tick("BTC-USD", "63000", event_time=t0 + timedelta(seconds=10)))

        pct_alerts = [
            e for e in received if e.payload["payload"].get("alert_type") == "pct_move"
        ]
        assert pct_alerts == []

    async def test_does_not_fire_on_small_move(self, bus_and_gen: tuple) -> None:
        bus, _ = bus_and_gen
        received: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            received.append(env)

        await bus.subscribe(EventType.SIGNAL_CREATED, handler)

        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        await bus.publish(_tick("BTC-USD", "60000", event_time=t0))
        # 1% move — below 3% threshold
        await bus.publish(_tick("BTC-USD", "60600", event_time=t0 + timedelta(minutes=5)))

        pct_alerts = [
            e for e in received if e.payload["payload"].get("alert_type") == "pct_move"
        ]
        assert pct_alerts == []
