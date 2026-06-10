"""
Tests for FeedRouter: routing watchlist changes to the correct feed adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventEnvelope, EventType
from ingestion.router import FeedRouter
from watchlist.store import WatchlistEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _setup():
    event_store = InMemoryEventStore()
    bus = InProcessBus(event_store)

    kraken = AsyncMock()
    equity = AsyncMock()

    return bus, kraken, equity


def _mock_watchlist(instruments: dict[str, str]) -> MagicMock:
    """Return a mock WatchlistManager with preset active_instruments and markets."""
    wl = MagicMock()
    wl.active_instruments = frozenset(instruments.keys())
    wl.get_market = lambda instrument: instruments.get(instrument, "crypto")
    return wl


def _added_envelope(instrument: str, market: str) -> EventEnvelope:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return EventEnvelope(
        event_type=EventType.WATCHLIST_INSTRUMENT_ADDED,
        source="watchlist_manager",
        event_time=now,
        ingest_time=now,
        payload={"instrument": instrument, "market": market},
    )


def _removed_envelope(instrument: str, market: str) -> EventEnvelope:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return EventEnvelope(
        event_type=EventType.WATCHLIST_INSTRUMENT_REMOVED,
        source="watchlist_manager",
        event_time=now,
        ingest_time=now,
        payload={"instrument": instrument, "market": market},
    )


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


class TestBootstrap:
    async def test_subscribes_crypto_instruments_on_start(self) -> None:
        bus, kraken, equity = await _setup()
        wl = _mock_watchlist({"BTC-USD": "crypto", "ETH-USD": "crypto"})

        router = FeedRouter(bus, wl, kraken, equity)
        await router.start()

        assert kraken.subscribe.call_count == 2
        instruments_called = {call.args[0] for call in kraken.subscribe.call_args_list}
        assert instruments_called == {"BTC-USD", "ETH-USD"}
        equity.subscribe.assert_not_called()

    async def test_subscribes_equity_instruments_on_start(self) -> None:
        bus, kraken, equity = await _setup()
        wl = _mock_watchlist({"AAPL": "equity", "MSFT": "equity"})

        router = FeedRouter(bus, wl, kraken, equity)
        await router.start()

        assert equity.subscribe.call_count == 2
        instruments_called = {call.args[0] for call in equity.subscribe.call_args_list}
        assert instruments_called == {"AAPL", "MSFT"}
        kraken.subscribe.assert_not_called()

    async def test_subscribes_mixed_instruments_on_start(self) -> None:
        bus, kraken, equity = await _setup()
        wl = _mock_watchlist({"BTC-USD": "crypto", "AAPL": "equity"})

        router = FeedRouter(bus, wl, kraken, equity)
        await router.start()

        kraken.subscribe.assert_called_once_with("BTC-USD")
        equity.subscribe.assert_called_once_with("AAPL")

    async def test_empty_watchlist_on_start(self) -> None:
        bus, kraken, equity = await _setup()
        wl = _mock_watchlist({})

        router = FeedRouter(bus, wl, kraken, equity)
        await router.start()

        kraken.subscribe.assert_not_called()
        equity.subscribe.assert_not_called()


# ---------------------------------------------------------------------------
# Dynamic add via bus events
# ---------------------------------------------------------------------------


class TestHandleAdded:
    async def test_routes_crypto_to_kraken(self) -> None:
        bus, kraken, equity = await _setup()
        wl = _mock_watchlist({})

        router = FeedRouter(bus, wl, kraken, equity)
        await router.start()
        kraken.subscribe.reset_mock()

        await router._handle_added(_added_envelope("SOL-USD", "crypto"))

        kraken.subscribe.assert_called_once_with("SOL-USD")
        equity.subscribe.assert_not_called()

    async def test_routes_equity_to_equity_feed(self) -> None:
        bus, kraken, equity = await _setup()
        wl = _mock_watchlist({})

        router = FeedRouter(bus, wl, kraken, equity)
        await router.start()

        await router._handle_added(_added_envelope("TSLA", "equity"))

        equity.subscribe.assert_called_once_with("TSLA")
        kraken.subscribe.assert_not_called()

    async def test_no_equity_feed_logs_warning(self) -> None:
        bus, kraken, _ = await _setup()
        wl = _mock_watchlist({})

        router = FeedRouter(bus, wl, kraken, equity_feed=None)
        await router.start()

        # Should not raise even without equity feed
        await router._handle_added(_added_envelope("AAPL", "equity"))
        kraken.subscribe.assert_not_called()

    async def test_empty_instrument_ignored(self) -> None:
        bus, kraken, equity = await _setup()
        wl = _mock_watchlist({})

        router = FeedRouter(bus, wl, kraken, equity)
        await router.start()

        await router._handle_added(_added_envelope("", "crypto"))

        kraken.subscribe.assert_not_called()


# ---------------------------------------------------------------------------
# Dynamic remove via bus events
# ---------------------------------------------------------------------------


class TestHandleRemoved:
    async def test_unsubscribes_crypto_from_kraken(self) -> None:
        bus, kraken, equity = await _setup()
        wl = _mock_watchlist({"BTC-USD": "crypto"})

        router = FeedRouter(bus, wl, kraken, equity)
        await router.start()

        await router._handle_removed(_removed_envelope("BTC-USD", "crypto"))

        kraken.unsubscribe.assert_called_once_with("BTC-USD")
        equity.unsubscribe.assert_not_called()

    async def test_unsubscribes_equity_from_equity_feed(self) -> None:
        bus, kraken, equity = await _setup()
        wl = _mock_watchlist({"AAPL": "equity"})

        router = FeedRouter(bus, wl, kraken, equity)
        await router.start()

        await router._handle_removed(_removed_envelope("AAPL", "equity"))

        equity.unsubscribe.assert_called_once_with("AAPL")
        kraken.unsubscribe.assert_not_called()

    async def test_no_equity_feed_remove_equity_no_raise(self) -> None:
        bus, kraken, _ = await _setup()
        wl = _mock_watchlist({})

        router = FeedRouter(bus, wl, kraken, equity_feed=None)
        await router.start()

        # Should not raise
        await router._handle_removed(_removed_envelope("AAPL", "equity"))
        kraken.unsubscribe.assert_not_called()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_stop_unsubscribes_from_bus(self) -> None:
        bus, kraken, equity = await _setup()
        wl = _mock_watchlist({})

        router = FeedRouter(bus, wl, kraken, equity)
        await router.start()

        # After start, router should have two bus subscriptions (added + removed)
        assert len(router._subs) == 2

        await router.stop()
        assert len(router._subs) == 0

    async def test_bus_events_not_received_after_stop(self) -> None:
        bus, kraken, equity = await _setup()
        wl = _mock_watchlist({})

        router = FeedRouter(bus, wl, kraken, equity)
        await router.start()
        await router.stop()
        kraken.subscribe.reset_mock()

        # Publish a watchlist event — router should not react
        await bus.publish(_added_envelope("BTC-USD", "crypto"))

        kraken.subscribe.assert_not_called()
