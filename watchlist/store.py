"""
WatchlistStore — persistence for the user's active instrument set.

Protocol + SqliteWatchlistStore.  A PostgresWatchlistStore is a future
drop-in: all raw SQL lives here; callers only see the protocol.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple, Protocol, runtime_checkable

if TYPE_CHECKING:
    import aiosqlite


class WatchlistEntry(NamedTuple):
    instrument: str
    market: str        # "crypto" | "equity"
    added_at: datetime


@runtime_checkable
class WatchlistStore(Protocol):
    async def add(self, instrument: str, market: str) -> None: ...
    async def remove(self, instrument: str) -> None: ...
    async def list_active(self) -> list[WatchlistEntry]: ...


class SqliteWatchlistStore:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def add(self, instrument: str, market: str = "crypto") -> None:
        now = datetime.now(UTC).isoformat()
        await self._conn.execute(
            "INSERT OR IGNORE INTO watchlist (instrument, market, added_at, enabled) VALUES (?, ?, ?, 1)",
            (instrument, market, now),
        )
        # Re-enable and update market if it already existed but was disabled.
        await self._conn.execute(
            "UPDATE watchlist SET enabled = 1, market = ? WHERE instrument = ?",
            (market, instrument),
        )
        await self._conn.commit()

    async def remove(self, instrument: str) -> None:
        await self._conn.execute(
            "DELETE FROM watchlist WHERE instrument = ?",
            (instrument,),
        )
        await self._conn.commit()

    async def list_active(self) -> list[WatchlistEntry]:
        cursor = await self._conn.execute(
            "SELECT instrument, market, added_at FROM watchlist WHERE enabled = 1 ORDER BY added_at",
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            WatchlistEntry(
                instrument=row[0],
                market=row[1],
                added_at=datetime.fromisoformat(row[2]),
            )
            for row in rows
        ]
