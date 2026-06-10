"""
Tests for SqliteWatchlistStore against a real in-memory SQLite DB.
"""

from __future__ import annotations

import pytest

from core.db import migrate, open_db
from watchlist.store import SqliteWatchlistStore


@pytest.fixture
async def store():
    conn = await open_db(":memory:")
    await migrate(conn)
    yield SqliteWatchlistStore(conn)
    await conn.close()


class TestAdd:
    async def test_add_new_instrument(self, store: SqliteWatchlistStore) -> None:
        await store.add("BTC-USD", "crypto")
        entries = await store.list_active()
        assert len(entries) == 1
        assert entries[0].instrument == "BTC-USD"
        assert entries[0].market == "crypto"

    async def test_add_equity_instrument(self, store: SqliteWatchlistStore) -> None:
        await store.add("AAPL", "equity")
        entries = await store.list_active()
        assert entries[0].market == "equity"

    async def test_add_idempotent(self, store: SqliteWatchlistStore) -> None:
        await store.add("BTC-USD", "crypto")
        await store.add("BTC-USD", "crypto")
        entries = await store.list_active()
        assert len(entries) == 1

    async def test_add_multiple(self, store: SqliteWatchlistStore) -> None:
        await store.add("BTC-USD", "crypto")
        await store.add("ETH-USD", "crypto")
        await store.add("AAPL", "equity")
        entries = await store.list_active()
        assert {e.instrument for e in entries} == {"BTC-USD", "ETH-USD", "AAPL"}

    async def test_re_enable_removed_instrument(self, store: SqliteWatchlistStore) -> None:
        await store.add("BTC-USD", "crypto")
        await store.remove("BTC-USD")
        assert await store.list_active() == []

        await store.add("BTC-USD", "crypto")
        entries = await store.list_active()
        assert len(entries) == 1
        assert entries[0].instrument == "BTC-USD"

    async def test_add_updates_market_on_re_add(self, store: SqliteWatchlistStore) -> None:
        await store.add("BTC-USD", "crypto")
        await store.remove("BTC-USD")
        await store.add("BTC-USD", "equity")
        entries = await store.list_active()
        assert entries[0].market == "equity"


class TestRemove:
    async def test_remove_existing(self, store: SqliteWatchlistStore) -> None:
        await store.add("ETH-USD", "crypto")
        await store.remove("ETH-USD")
        assert await store.list_active() == []

    async def test_remove_nonexistent_is_noop(self, store: SqliteWatchlistStore) -> None:
        await store.remove("DOES-NOT-EXIST")
        assert await store.list_active() == []

    async def test_remove_only_targets_instrument(self, store: SqliteWatchlistStore) -> None:
        await store.add("BTC-USD", "crypto")
        await store.add("ETH-USD", "crypto")
        await store.remove("BTC-USD")
        entries = await store.list_active()
        assert [e.instrument for e in entries] == ["ETH-USD"]


class TestListActive:
    async def test_empty_store(self, store: SqliteWatchlistStore) -> None:
        assert await store.list_active() == []

    async def test_ordered_by_added_at(self, store: SqliteWatchlistStore) -> None:
        await store.add("ETH-USD", "crypto")
        await store.add("BTC-USD", "crypto")
        entries = await store.list_active()
        assert entries[0].instrument == "ETH-USD"
        assert entries[1].instrument == "BTC-USD"

    async def test_added_at_is_datetime(self, store: SqliteWatchlistStore) -> None:
        from datetime import datetime
        await store.add("BTC-USD", "crypto")
        entries = await store.list_active()
        assert isinstance(entries[0].added_at, datetime)
        assert entries[0].added_at.tzinfo is not None
