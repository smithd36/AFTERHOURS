"""build_equity_curve — daily mark-to-market projection over fills + ticks."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from analytics import EquityPoint, build_equity_curve
from core.schemas.events import EventEnvelope, EventType
from portfolio.settings import PortfolioSettings

SETTINGS = PortfolioSettings(initial_cash=Decimal("10000"))


def _at(d: str) -> datetime:
    return datetime.fromisoformat(d).replace(tzinfo=UTC)


def _fill(day: str, action: str, price: str, *, side: str = "long") -> EventEnvelope:
    t = _at(day)
    return EventEnvelope(
        event_type=EventType.ORDER_FILLED,
        source="paper_executor",
        event_time=t,
        ingest_time=t,
        payload={
            "instrument": "BTC-USD",
            "action": action,
            "side": side,
            "fill_price": price,
            "quantity": "1",
            "cost_usd": price,
            "fee": "0",
            "decision_id": "d1",
        },
    )


def _tick(day: str, price: str) -> EventEnvelope:
    t = _at(day)
    return EventEnvelope(
        event_type=EventType.MARKET_TICK,
        source="kraken",
        event_time=t,
        ingest_time=t,
        payload={"instrument": "BTC-USD", "price": price},
    )


async def test_empty_history_is_empty_curve() -> None:
    assert await build_equity_curve([], [], today=date(2026, 6, 3)) == []


async def test_open_mark_close_curve() -> None:
    """Long opened day 1 at 100 (no tick → marks at entry), marked up to 120 on
    day 2, closed day 3. Equity: 10000 → 10020 → 10020."""
    fills = [
        _fill("2026-06-01T15:00", "open", "100"),
        _fill("2026-06-03T15:00", "close", "120"),
    ]
    ticks = [_tick("2026-06-02T20:00", "120")]

    points = await build_equity_curve(
        fills, ticks, today=date(2026, 6, 3), settings=SETTINGS
    )

    assert points == [
        EquityPoint(date(2026, 6, 1), Decimal("10000")),  # marked at entry
        EquityPoint(date(2026, 6, 2), Decimal("10020")),  # +20 unrealized
        EquityPoint(date(2026, 6, 3), Decimal("10020")),  # +20 realized, flat cash
    ]


async def test_mark_carries_forward_when_no_tick_that_day() -> None:
    """A day with no tick reuses the last known price (here the day-2 mark of
    120 persists into day 3 while the position stays open)."""
    fills = [_fill("2026-06-01T15:00", "open", "100")]
    ticks = [_tick("2026-06-02T20:00", "120")]

    points = await build_equity_curve(
        fills, ticks, today=date(2026, 6, 3), settings=SETTINGS
    )

    assert [p.equity for p in points] == [
        Decimal("10000"),  # day 1: entry mark
        Decimal("10020"),  # day 2: tick 120
        Decimal("10020"),  # day 3: carries 120 forward
    ]


async def test_short_position_loses_as_price_rises() -> None:
    """A short marked against a rising price reduces equity (sign-correct, not
    sign-blind market value)."""
    fills = [_fill("2026-06-01T15:00", "open", "100", side="short")]
    ticks = [_tick("2026-06-02T20:00", "130")]

    points = await build_equity_curve(
        fills, ticks, today=date(2026, 6, 2), settings=SETTINGS
    )

    # short unrealized = (entry - current) * qty = (100 - 130) = -30
    assert points[-1].equity == Decimal("9970")


@pytest.mark.parametrize("n", [1, 2, 5])
async def test_one_point_per_calendar_day(n: int) -> None:
    fills = [_fill("2026-06-01T15:00", "open", "100")]
    today = date(2026, 6, n)
    points = await build_equity_curve(fills, [], today=today, settings=SETTINGS)
    assert len(points) == n
    assert points[0].day == date(2026, 6, 1)
    assert points[-1].day == today
