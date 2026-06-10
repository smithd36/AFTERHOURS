# Phase 5 Implementation Plan — Watchlist & Multi-Instrument Scale

> **Status: DELIVERED (2026-06-10)**
>
> All workstreams below were implemented. Additional work completed beyond the original plan: watchlist-scoped signal/thesis/decision filtering with live backfill-on-add, per-instrument feed-status indicator in WatchlistPanel, search/filter box in WatchlistPanel, empty-watchlist full suppression (no phantom news), and frontend watchlist sync extended to MarketWatch, ThesisFeed, and DecisionQueue panels.

> **Scope:** user-managed instrument watchlist, instrument-agnostic feed routing (crypto + equity stub), pipeline filtering, tick retention, and Postgres-readiness seams. No live trading, no real money — those are Phase 6.

The phase has four workstreams. Watchlist store (A) comes first because everything else depends on the active instrument set.

---

## Workstream A — Watchlist store & manager

### A1. DB migration

New migration `core/db/migrations/002_create_watchlist.sql`:

```sql
CREATE TABLE IF NOT EXISTS watchlist (
    instrument   TEXT PRIMARY KEY,
    added_at     TEXT NOT NULL,   -- ISO-8601 UTC
    enabled      INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS watchlist_enabled ON watchlist (enabled);
```

Uses ANSI SQL — compatible with both SQLite and Postgres.

### A2. `WatchlistStore` protocol + `SqliteWatchlistStore`

New package `watchlist/`. Protocol in `watchlist/store.py`:

```python
class WatchlistStore(Protocol):
    async def add(self, instrument: str) -> None: ...
    async def remove(self, instrument: str) -> None: ...
    async def list_active(self) -> list[str]: ...
```

`SqliteWatchlistStore` implements this against the `watchlist` table. All raw SQL lives here — `PostgresWatchlistStore` is a future drop-in with no changes to callers.

### A3. `WatchlistManager`

`watchlist/manager.py` — loads active instruments on startup, exposes `active_instruments: frozenset[str]`, publishes `watchlist.instrument_added` / `watchlist.instrument_removed` onto the bus when add/remove is called. Seed defaults (`WATCHLIST_DEFAULT_INSTRUMENTS`, comma-separated env var) are inserted on first run if the table is empty.

Add `EventType.WATCHLIST_INSTRUMENT_ADDED` and `WATCHLIST_INSTRUMENT_REMOVED` to `core/schemas/events.py` (and mirror in `frontend/src/types/core.ts`).

### A4. REST API

`gateway/routes/watchlist.py`:

| Endpoint | Description |
|---|---|
| `GET /api/watchlist` | List active instruments |
| `POST /api/watchlist` | Add instrument `{"instrument": "AAPL"}` |
| `DELETE /api/watchlist/{instrument}` | Remove instrument |

---

## Workstream B — Instrument-agnostic feed routing

### B1. `KrakenFeed` — dynamic subscribe/unsubscribe

Add `subscribe(instrument: str)` and `unsubscribe(instrument: str)` to `KrakenFeed`. Both send the appropriate Kraken v2 WS message on the live connection:

```json
{"method": "subscribe",   "params": {"channel": "ticker", "symbol": ["BTC/USD"]}}
{"method": "unsubscribe", "params": {"channel": "ticker", "symbol": ["BTC/USD"]}}
```

No reconnect needed — Kraken v2 supports dynamic channel management. The existing static subscription at startup remains; dynamic calls extend it at runtime.

### B2. `EquityFeed` stub

New `ingestion/equity/feed.py` — REST polling adapter. On each tick interval (`EQUITY_POLL_INTERVAL_SECONDS`, default 60), calls the configured provider REST endpoint for each watched equity instrument and emits `EventEnvelope(MARKET_TICK)` with the same schema as `KrakenFeed`.

Provider selection via `EQUITY_DATA_PROVIDER` env var: `alpaca` (free tier, delayed) or `polygon` (free tier, delayed). Both are behind a `EquityDataSource` ABC — adding a WS-backed provider in Phase 7 is a drop-in. If no provider is configured, `EquityFeed` runs in no-op mode (logs a warning; the watchlist still works for crypto-only setups).

### B3. `FeedRouter`

`ingestion/router.py` — subscribes to `watchlist.instrument_added` and `watchlist.instrument_removed`. On add: classifies the instrument as crypto (`*-USD` Kraken-style) or equity (everything else) and calls the appropriate feed adapter's `subscribe()`. On remove: calls `unsubscribe()`. Bootstraps on startup by subscribing to all currently active instruments from `WatchlistManager.active_instruments`.

Instrument classification is a simple heuristic for Phase 5 (regex on symbol format). Phase 7 can introduce a proper instrument metadata store.

---

## Workstream C — Pipeline filtering

Single change per component: receive `WatchlistManager` on construction, check `instrument in manager.active_instruments` before processing.

| Component | Change |
|---|---|
| `PriceAlertGenerator` | Skip `market.tick` for unwatched instruments |
| `ThesisGenerator` | Skip `signal.created` for unwatched instruments |
| `DecisionGenerator` | Skip `thesis.created` for unwatched instruments (already keyed by instrument) |
| `OutcomeResolver` | Skip `decision.proposed` for unwatched instruments (already keyed by instrument — low-priority, decisions are already scoped) |

No change needed to `RiskEngine`, `Portfolio`, `CalibrationEngine` — they already process only what reaches them.

---

## Workstream D — Tick retention & Postgres-readiness

### D1. `TickPruner`

`ingestion/pruner.py` — background task that runs every `TICK_PRUNE_INTERVAL_HOURS` (default 24). Deletes `market.tick` events from the event store older than `TICK_RETENTION_DAYS` (default 30). Uses a new `EventStore.prune(event_types, before)` method added to the protocol (both `InMemoryEventStore` and `SqliteEventStore` implement it; `InMemoryEventStore.prune` is a no-op in tests).

```sql
DELETE FROM events
WHERE event_type = 'market.tick'
  AND event_time < ?;
```

### D2. Frontend — `WatchlistPanel`

New `components/panels/WatchlistPanel.tsx`:
- Search box (filter by symbol as you type)
- List of active instruments with remove button
- Add field for new instrument
- Live feedback: shows feed status per instrument (subscribing / active / error) via `watchlist.*` events on the WS

`useWatchlist` hook: REST snapshot from `GET /api/watchlist` on mount + live updates from `watchlist.instrument_added` / `watchlist.instrument_removed` WS events.

---

## Milestones

| # | Deliverable | Done when |
|---|---|---|
| M1 | Watchlist store + API | `GET/POST/DELETE /api/watchlist` persists and returns instruments; seeds defaults on first run |
| M2 | Dynamic feed routing | Adding BTC-USD to the watchlist via the API causes `KrakenFeed` to subscribe at runtime; removing it unsubscribes |
| M3 | Pipeline filtering | Signals, theses, and decisions are only generated for instruments in the active watchlist |
| M4 | Equity stub | Adding a stock ticker (e.g. `AAPL`) to the watchlist causes `EquityFeed` to poll and emit `market.tick` events |
| M5 | Tick retention | `TickPruner` runs on schedule and the event store does not grow unboundedly with a large watchlist |
| M6 | WatchlistPanel | Operator can add/remove instruments from the terminal UI; feed status is visible per instrument |
| M7 | Phase exit | Any Kraken crypto or supported equity can be added to the watchlist at runtime; the full pipeline (feeds → signals → thesis → decision → calibration) is scoped to watched instruments; DB growth is bounded |

---

## Non-goals (Phase 6+)

Live broker adapter, real-money execution, broker reconciliation, full equities market-hours enforcement (Phase 7), PDT rules (Phase 7), Postgres migration (Phase 7 trigger if SQLite becomes a bottleneck).

## Open questions / risks

- **Equity provider choice:** Alpaca vs Polygon free tier — confirm rate limits before M4. If both are too restrictive, the stub can be a simulated feed (fixed prices from a seed file) for Phase 5 and replaced in Phase 7.
- **Kraken symbol format:** Kraken v2 uses `BTC/USD` internally but the rest of the system uses `BTC-USD`. The normalizer already handles this (`/` → `-`); ensure the dynamic subscribe call translates correctly in both directions.
- **Watchlist size limits:** no hard cap in Phase 5. Monitor SQLite write throughput with >50 active instruments; document the observed limit as input for the Phase 7 Postgres decision.
- **Cold-start with large watchlist:** on restart, `FeedRouter` must re-subscribe all active instruments. With 50+ instruments this is a burst of WS messages — add a small jitter/backoff to avoid rate-limiting Kraken at startup.
