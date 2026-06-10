"""
Tests for WatchlistManager.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.events import EventType
from watchlist.manager import WatchlistManager
from watchlist.settings import WatchlistSettings
from watchlist.store import SqliteWatchlistStore, WatchlistEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_bus():
    store = InMemoryEventStore()
    bus = InProcessBus(store)
    return bus, store


def _settings(instruments: list[str] = None, market: str = "crypto") -> WatchlistSettings:
    return WatchlistSettings(
        default_instruments=instruments or ["BTC-USD", "ETH-USD"],
        default_market=market,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSeeding:
    async def test_seeds_defaults_when_store_empty(self) -> None:
        bus, _ = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.side_effect = [
            [],  # first call: empty → trigger seeding
            [
                WatchlistEntry("BTC-USD", "crypto", __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)),
                WatchlistEntry("ETH-USD", "crypto", __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)),
            ],
        ]
        settings = _settings(["BTC-USD", "ETH-USD"])
        manager = WatchlistManager(bus, wl_store, settings)
        await manager.start()

        assert wl_store.add.call_count == 2
        assert manager.active_instruments == frozenset({"BTC-USD", "ETH-USD"})

    async def test_no_seeding_when_store_populated(self) -> None:
        from datetime import UTC, datetime
        bus, _ = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.return_value = [
            WatchlistEntry("SOL-USD", "crypto", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
        manager = WatchlistManager(bus, wl_store, _settings())
        await manager.start()

        wl_store.add.assert_not_called()
        assert manager.active_instruments == frozenset({"SOL-USD"})


class TestActiveInstruments:
    async def test_returns_frozenset(self) -> None:
        from datetime import UTC, datetime
        bus, _ = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.return_value = [
            WatchlistEntry("BTC-USD", "crypto", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
        manager = WatchlistManager(bus, wl_store, _settings())
        await manager.start()

        result = manager.active_instruments
        assert isinstance(result, frozenset)
        assert "BTC-USD" in result

    async def test_get_market_known_instrument(self) -> None:
        from datetime import UTC, datetime
        bus, _ = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.return_value = [
            WatchlistEntry("AAPL", "equity", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
        manager = WatchlistManager(bus, wl_store, _settings())
        await manager.start()

        assert manager.get_market("AAPL") == "equity"

    async def test_get_market_unknown_defaults_to_crypto(self) -> None:
        bus, _ = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.return_value = []
        wl_store.add = AsyncMock()
        wl_store.list_active.side_effect = [[], []]
        manager = WatchlistManager(bus, wl_store, _settings([]))
        await manager.start()

        assert manager.get_market("UNKNOWN-USD") == "crypto"


class TestAdd:
    async def test_add_updates_active_instruments(self) -> None:
        from datetime import UTC, datetime
        bus, _ = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.return_value = [
            WatchlistEntry("BTC-USD", "crypto", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
        manager = WatchlistManager(bus, wl_store, _settings())
        await manager.start()

        await manager.add("SOL-USD", "crypto")
        assert "SOL-USD" in manager.active_instruments

    async def test_add_publishes_event(self) -> None:
        from datetime import UTC, datetime
        bus, event_store = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.return_value = [
            WatchlistEntry("BTC-USD", "crypto", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
        manager = WatchlistManager(bus, wl_store, _settings())
        await manager.start()

        await manager.add("SOL-USD", "crypto")

        events = event_store.events
        added_events = [e for e in events if e.event_type == EventType.WATCHLIST_INSTRUMENT_ADDED.value]
        assert len(added_events) == 1
        assert added_events[0].payload["instrument"] == "SOL-USD"
        assert added_events[0].payload["market"] == "crypto"

    async def test_add_persists_to_store(self) -> None:
        from datetime import UTC, datetime
        bus, _ = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.return_value = [
            WatchlistEntry("BTC-USD", "crypto", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
        manager = WatchlistManager(bus, wl_store, _settings())
        await manager.start()

        await manager.add("AAPL", "equity")
        wl_store.add.assert_called_once_with("AAPL", "equity")


class TestRemove:
    async def test_remove_updates_active_instruments(self) -> None:
        from datetime import UTC, datetime
        bus, _ = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.return_value = [
            WatchlistEntry("BTC-USD", "crypto", datetime(2026, 1, 1, tzinfo=UTC)),
            WatchlistEntry("ETH-USD", "crypto", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
        manager = WatchlistManager(bus, wl_store, _settings())
        await manager.start()

        await manager.remove("BTC-USD")
        assert "BTC-USD" not in manager.active_instruments
        assert "ETH-USD" in manager.active_instruments

    async def test_remove_publishes_event(self) -> None:
        from datetime import UTC, datetime
        bus, event_store = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.return_value = [
            WatchlistEntry("BTC-USD", "crypto", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
        manager = WatchlistManager(bus, wl_store, _settings())
        await manager.start()

        await manager.remove("BTC-USD")

        events = event_store.events
        removed_events = [e for e in events if e.event_type == EventType.WATCHLIST_INSTRUMENT_REMOVED.value]
        assert len(removed_events) == 1
        assert removed_events[0].payload["instrument"] == "BTC-USD"

    async def test_remove_persists_to_store(self) -> None:
        from datetime import UTC, datetime
        bus, _ = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.return_value = [
            WatchlistEntry("BTC-USD", "crypto", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
        manager = WatchlistManager(bus, wl_store, _settings())
        await manager.start()

        await manager.remove("BTC-USD")
        wl_store.remove.assert_called_once_with("BTC-USD")

    async def test_remove_nonexistent_does_not_raise(self) -> None:
        from datetime import UTC, datetime
        bus, _ = await _make_bus()
        wl_store = AsyncMock()
        wl_store.list_active.return_value = [
            WatchlistEntry("BTC-USD", "crypto", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
        manager = WatchlistManager(bus, wl_store, _settings())
        await manager.start()

        # Should not raise even if instrument not in active set
        await manager.remove("DOES-NOT-EXIST")
