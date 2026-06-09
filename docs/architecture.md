# Architecture

AFTERHOURS is a **modular monolith** — all subsystems run in one process, communicate through an in-memory event bus, and share a single SQLite database. The architecture is designed to extract individual subsystems to separate services when throughput or isolation demands it, without changing the application-level contract.

---

## Component Overview

### `core/`

The shared kernel. No dependency on any subsystem.

| Module | Responsibility |
|---|---|
| `core/schemas/common.py` | `Instrument`, `Provenance`, `Money` — canonical domain types |
| `core/schemas/signal.py` | `Signal` (provenance-tagged, payload marked untrusted), `Thesis` |
| `core/schemas/decision.py` | `Decision` and all sub-objects — the central artifact |
| `core/schemas/events.py` | `EventEnvelope`, `EventType` enum (31 topics), `AutonomyMode` |
| `core/bus/` | `Bus` ABC, `InProcessBus`, `EventStore` protocol, adapters |
| `core/db/` | aiosqlite connection factory, migration runner |
| `core/logging.py` | structlog with stdlib bridge, dev + JSON render modes |

### `ingestion/`

Market data feeds. Each feed is a `Feed` ABC implementation that runs forever, reconnects on error, and stops cleanly on `asyncio.CancelledError`.

| Module | Responsibility |
|---|---|
| `ingestion/coinbase/feed.py` | Coinbase Advanced Trade public WebSocket, tenacity reconnect |
| `ingestion/coinbase/normalizer.py` | Raw Coinbase messages → `EventEnvelope(MARKET_TICK)` |
| `ingestion/coinbase/settings.py` | `COINBASE_WS_URL`, `COINBASE_PRODUCTS` env config |

### `gateway/`

The FastAPI application. Exposes HTTP endpoints and the WebSocket feed. Manages the application lifespan.

| Module | Responsibility |
|---|---|
| `gateway/app.py` | `create_app()` factory, `default_lifespan`, routes |
| `gateway/broadcaster.py` | `Broadcaster` — subscribes to bus, fans out to WS clients |
| `gateway/settings.py` | `HOST`, `PORT`, `CORS_ORIGINS` env config |

### `frontend/`

React terminal UI built with Vite, TypeScript, Tailwind CSS v4, and shadcn/ui (new-york style, zinc base).

| Module | Responsibility |
|---|---|
| `hooks/useEventStream.ts` | WS connection to `/ws`, exponential backoff reconnect |
| `hooks/useMarketTicks.ts` | `useReducer`-backed tick map; dispatches on `market.tick` |
| `components/panels/MarketWatch.tsx` | Live tick table with bullish/bearish price colouring |
| `components/layout/PanelShell.tsx` | Reusable terminal panel (header bar + content slot) |
| `types/core.ts` | TypeScript mirror of `core/schemas/*.py` |

---

## Data Flow

### Market tick (Phase 0)

```
1. CoinbaseFeed._stream()
   └─ websockets.connect("wss://advanced-trade-ws.coinbase.com/ws")
   └─ subscribe({"type":"subscribe","channel":"ticker","product_ids":[...]})

2. CoinbaseNormalizer.normalize(raw_message)
   └─ produces EventEnvelope(
        event_type = "market.tick",
        event_time = parsed venue timestamp,   ← financial clock
        ingest_time = datetime.now(UTC),        ← our clock
        payload = { instrument, price, best_bid, best_ask, ... }
      )

3. InProcessBus.publish(envelope)
   ├─ SqliteEventStore.append(envelope)         ← persist FIRST
   └─ asyncio.gather(*[handler(envelope) for handler in subscribers])

4. Broadcaster._fanout(envelope)
   └─ for each connected WebSocket client:
        client.send_text(envelope.model_dump_json())

5. useEventStream (browser)
   └─ JSON.parse(event.data) → EventEnvelope
   └─ dispatch to useMarketTicks if event_type === "market.tick"

6. MarketWatch re-renders with updated tick row
```

### Event persistence

Every event is appended to the `events` table **before** fan-out. The event store is the authoritative audit log. If a subscriber crashes mid-delivery, events can be replayed from the table.

```sql
CREATE TABLE events (
  id           TEXT PRIMARY KEY,
  event_type   TEXT NOT NULL,
  source       TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  event_time   TEXT NOT NULL,   -- ISO-8601 UTC (financial clock)
  ingest_time  TEXT NOT NULL,   -- ISO-8601 UTC (our clock)
  correlation_id TEXT,
  payload      TEXT NOT NULL    -- JSON
);
```

Three indexes cover the common query patterns:
- `event_time DESC` — timeline view
- `(event_type, event_time DESC)` — per-topic queries
- `correlation_id WHERE NOT NULL` — full decision lifecycle reconstruction

---

## Event Bus

### Topic naming

```
{domain}.{verb}
```

Full registry in `core/schemas/events.py` (`EventType` enum) and mirrored in `frontend/src/types/core.ts`.

| Domain | Topics |
|---|---|
| `market` | `tick`, `orderbook`, `ohlcv` |
| `signal` | `created`, `updated` |
| `thesis` | `created`, `updated`, `invalidated` |
| `decision` | `proposed`, `approved`, `rejected`, `expired`, `executing`, `executed`, `failed` |
| `order` | `submitted`, `filled`, `partially_filled`, `cancelled`, `failed` |
| `portfolio` | `position_updated`, `reconciled`, `reconciliation_failed` |
| `risk` | `limit_approached`, `limit_breached`, `halt` |
| `system` | `feed_healthy`, `feed_degraded`, `feed_dead`, `mode_changed`, `error` |

### Subscription patterns

| Pattern | Matches |
|---|---|
| `"market.tick"` | Exact topic only |
| `"decision.*"` | All `decision.*` topics |
| `"*"` | Every event (used by Broadcaster, audit sink) |

### Two-clock invariant

`EventEnvelope` carries two timestamps. **Never mix them.**

| Field | Clock | Used for |
|---|---|---|
| `event_time` | Source / venue | All financial logic, point-in-time features, backtesting |
| `ingest_time` | Our process | Operational monitoring, latency measurement, debugging |

Confusing them is a source of look-ahead bias. The rule is enforced by naming — application code that uses `ingest_time` for financial decisions is a bug.

---

## The Decision Object

`Decision` is the load-bearing domain object. Every trade recommendation is a `Decision` instance that lives immutably once created. Status transitions are new events, not mutations.

```
Decision
├── id                      UUID — also the correlation_id for all lifecycle events
├── originating_thesis_id   which Thesis triggered this (nullable)
├── input_signal_ids        point-in-time snapshot — enables deterministic audit replay
├── model: ModelInfo
│   └── prompt_hash         sha256 of fully-rendered prompt — locks reasoning to exact call
├── proposal: Proposal
│   └── size_usd            set by sizing code, NEVER by the LLM
├── reasoning               LLM-generated
├── evidence[]              each item cites a real Signal.id
├── confidence              0–1
├── risk: RiskAssessment
│   └── risk_engine_verdict  authoritative — overrides LLM confidence
├── status                  proposed → approved/rejected → executing → executed/failed
├── human: HumanAction      approval, rejection, or edit record
└── outcome: DecisionOutcome fills, realised P&L, slippage
```

**Separation of duties enforced in the schema:** the LLM's contribution is scoped to `reasoning`, `evidence[]`, `confidence`, and the directional elements of `Proposal`. Size is computed deterministically. Risk verdict is computed deterministically. The LLM cannot unilaterally commit capital.

---

## Frontend Design System

| Token | Value | Semantic meaning |
|---|---|---|
| `--bullish` | `oklch(0.65 0.18 145)` | green — positive price change |
| `--bearish` | `oklch(0.55 0.22 27)` | red — negative price change |
| `--warning` | `oklch(0.75 0.18 85)` | amber — degraded feed, caution |
| `--info` | `oklch(0.65 0.14 240)` | blue — informational |
| `--background` | `oklch(0.11 0 0)` | near-black terminal background |

Font stack: Geist Mono → JetBrains Mono → Fira Code → ui-monospace. The terminal is always dark; light mode is not a design target.

---

## Planned Subsystems (not yet built)

| Subsystem | Phase | Notes |
|---|---|---|
| Signal ingestion | 1 | News feed adapters, price-alert generator |
| LLM thesis layer | 2 | Thesis creation, invalidation condition tracking |
| Risk engine | 3 | Deterministic sizing, stop-loss, kill switch |
| Order execution | 4 | Paper trading first, then live via Coinbase Advanced Trade |
| Calibration engine | 5 | ECE measurement, autonomy promotion/demotion |
| Backtest harness | 5 | Replay event stream with mock adapters |
