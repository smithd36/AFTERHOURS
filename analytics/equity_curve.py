"""
Mark-to-market equity curve — a read-side projection over the event store.

Reconstructs end-of-day account equity by replaying the persisted
``order.filled`` history through the *same* ``Portfolio`` ledger math (so the
short-cash and fee arithmetic never drifts from the live book) and marking open
positions at each day's last known price from ``market.tick``. Event-time keyed,
so it reproduces identically under backtest replay; it adds no event type and no
stateful subscriber, and is computed on demand (ADR-011).

Days are *calendar* days, not NYSE sessions: the book mixes 24/7 crypto with
equities, so weekends carry real marks. Annualization in ``metrics`` therefore
uses 365.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, timedelta
from decimal import Decimal

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope
from portfolio.ledger import Portfolio
from portfolio.settings import PortfolioSettings


@dataclass(frozen=True)
class EquityPoint:
    day: date
    equity: Decimal


async def build_equity_curve(
    fills: list[EventEnvelope],
    ticks: list[EventEnvelope],
    *,
    today: date,
    settings: PortfolioSettings | None = None,
) -> list[EquityPoint]:
    """Daily mark-to-market equity from first fill through ``today``.

    ``fills`` and ``ticks`` must be ``order.filled`` / ``market.tick`` envelopes
    in event-time order (``EventStore.range`` returns them that way). Returns one
    point per calendar day; an empty list if there are no fills.
    """
    if not fills:
        return []

    # Throwaway ledger used purely as a calculator — never started, so it holds
    # no subscriptions; it reuses Portfolio's exact cash/position/short math.
    portfolio = Portfolio(InProcessBus(InMemoryEventStore()), settings)

    start_day = fills[0].event_time.astimezone(UTC).date()
    last_price: dict[str, Decimal] = {}
    points: list[EquityPoint] = []

    fi = ti = 0
    day = start_day
    while day <= today:
        # Apply every fill and tick that occurred on or before this day, in order.
        while fi < len(fills) and fills[fi].event_time.astimezone(UTC).date() <= day:
            # _handle_fill is the canonical replay entrypoint (the same one
            # Portfolio.rehydrate drives); it parses the envelope and routes
            # open/close. Reused here so the projection can never disagree with
            # the live ledger's arithmetic.
            await portfolio._handle_fill(fills[fi])
            fi += 1
        while ti < len(ticks) and ticks[ti].event_time.astimezone(UTC).date() <= day:
            p = ticks[ti].payload
            instrument = p.get("instrument", "")
            price_str = p.get("price", "")
            if instrument and price_str:
                last_price[instrument] = Decimal(str(price_str))
            ti += 1

        # Mark open positions to the day's last known price (carry-forward; an
        # instrument with no tick yet stays at its entry price → unrealized 0).
        for instrument, position in portfolio.positions.items():
            mark = last_price.get(instrument)
            if mark is not None:
                position.current_price = mark

        points.append(EquityPoint(day=day, equity=portfolio.total_value))
        day += timedelta(days=1)

    return points
