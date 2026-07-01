"""
Market-session awareness - keeps equity trading inside NYSE regular hours while
crypto stays live 24/7.

Used by the risk engine (reject an equity entry when its venue is closed) and the
paper executor (defer an equity close to the next session open instead of filling
at a stale last price). Crypto (Kraken / Coinbase) trades continuously, so the
gate is a no-op there. See docs/pre-phase-7-risk-review.md section 12.

Holidays and half-days are NOT modelled here - this is weekday + regular-hours
only. The authoritative source for holidays / early closes is the broker calendar
(Alpaca /v2/clock + /v2/calendar), wired with the live adapter in Phase 7A; until
then a weekday holiday reads as open (the equity feed returns the prior session's
snapshot, and the mark-freshness checks are the backstop).
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/New_York")

# NYSE regular trading hours (Eastern).
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def is_crypto(instrument: str) -> bool:
    """Canonical crypto symbols carry a quote suffix ("BTC-USD"); equities don't."""
    return "-" in instrument


def is_equity_market_open(at: datetime) -> bool:
    """True if `at` falls inside an NYSE regular-hours session (weekday 09:30-16:00 ET).

    `at` may be any timezone-aware instant; a naive value is assumed UTC. Holidays
    and half-days are not handled (see the module docstring)."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    et = at.astimezone(_EASTERN)
    if et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return MARKET_OPEN <= et.time() < MARKET_CLOSE


def is_market_open(instrument: str, at: datetime) -> bool:
    """True if `instrument`'s venue is open at `at`.

    Crypto is always open; equities follow NYSE regular hours. Callers pass an
    `event_time` (two-clock rule), so the gate stays point-in-time correct under
    backtest replay."""
    if is_crypto(instrument):
        return True
    return is_equity_market_open(at)
