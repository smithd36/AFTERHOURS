"""Market-session helper tests (core.market_hours)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.market_hours import is_crypto, is_equity_market_open, is_market_open

# Reference instants (June 2026, so Eastern = EDT = UTC-4):
#   2026-06-29 is a Monday.
_TUE_1400_ET = datetime(2026, 6, 30, 18, 0, tzinfo=UTC)   # Tue 14:00 ET - open
_TUE_0930_ET = datetime(2026, 6, 30, 13, 30, tzinfo=UTC)  # Tue 09:30 ET - open (boundary)
_TUE_1600_ET = datetime(2026, 6, 30, 20, 0, tzinfo=UTC)   # Tue 16:00 ET - closed (boundary)
_TUE_1900_ET = datetime(2026, 6, 30, 23, 0, tzinfo=UTC)   # Tue 19:00 ET - after-hours
_SAT_1400_ET = datetime(2026, 6, 27, 18, 0, tzinfo=UTC)   # Saturday - closed


def test_is_crypto_by_quote_suffix() -> None:
    assert is_crypto("BTC-USD")
    assert is_crypto("ETH-USD")
    assert not is_crypto("AAPL")
    assert not is_crypto("TSLA")


def test_equity_open_during_regular_hours() -> None:
    assert is_equity_market_open(_TUE_1400_ET)
    assert is_equity_market_open(_TUE_0930_ET)  # inclusive open


def test_equity_closed_outside_regular_hours() -> None:
    assert not is_equity_market_open(_TUE_1600_ET)  # exclusive close
    assert not is_equity_market_open(_TUE_1900_ET)  # after-hours
    assert not is_equity_market_open(_SAT_1400_ET)  # weekend


def test_naive_datetime_assumed_utc() -> None:
    assert is_equity_market_open(_TUE_1400_ET.replace(tzinfo=None))
    assert not is_equity_market_open(_SAT_1400_ET.replace(tzinfo=None))


def test_crypto_always_open() -> None:
    # Crypto trades 24/7, so the venue is open even on a weekend.
    assert is_market_open("BTC-USD", _SAT_1400_ET)
    assert is_market_open("ETH-USD", _TUE_1900_ET)


def test_equity_follows_session() -> None:
    assert is_market_open("AAPL", _TUE_1400_ET)
    assert not is_market_open("AAPL", _SAT_1400_ET)
    assert not is_market_open("AAPL", _TUE_1900_ET)
