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

Market data feeds and signal generators. Feeds run as long-lived async tasks; signal generators subscribe to the bus and react to events.

| Module | Responsibility |
|---|---|
| `ingestion/kraken/feed.py` | **Primary feed.** Kraken WebSocket v2, no auth required, tenacity reconnect |
| `ingestion/kraken/normalizer.py` | Raw Kraken messages → `EventEnvelope(MARKET_TICK)`. Normalises `BTC/USD` → `BTC-USD`. |
| `ingestion/kraken/settings.py` | `KRAKEN_WS_URL`, `KRAKEN_PRODUCTS` env config |
| `ingestion/coinbase/feed.py` | Coinbase Advanced Trade WebSocket (requires JWT auth — deferred to Phase 4) |
| `ingestion/coinbase/normalizer.py` | Raw Coinbase messages → `EventEnvelope(MARKET_TICK)` |
| `ingestion/coinbase/settings.py` | `COINBASE_WS_URL`, `COINBASE_PRODUCTS`, `COINBASE_API_KEY` env config |
| `ingestion/alerts/generator.py` | Subscribes to `market.tick`; emits `signal.created` for 24h crosses and short-window % moves |
| `ingestion/alerts/settings.py` | `ALERT_PRICE_MOVE_PCT_THRESHOLD`, `ALERT_COOLDOWN_MINUTES` env config |
| `ingestion/news/feed.py` | Polls RSS feeds (CoinDesk, CoinTelegraph) every 5 min; marks existing items on startup |
| `ingestion/news/normalizer.py` | RSS entry → `EventEnvelope(SIGNAL_CREATED)` with keyword-based instrument extraction |
| `ingestion/news/settings.py` | `NEWS_FEED_URLS`, `NEWS_POLL_INTERVAL_SECONDS` env config |

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
| `hooks/useSignals.ts` | Accumulates last 50 `signal.created` events; deduplicates by id |
| `components/panels/MarketWatch.tsx` | Live tick table with bullish/bearish price colouring |
| `components/panels/SignalFeed.tsx` | Scrollable signal list; PRICE/NEWS badges; relative-age labels |
| `components/layout/PanelShell.tsx` | Reusable terminal panel (header bar + content slot) |
| `types/core.ts` | TypeScript mirror of `core/schemas/*.py` |

---

## Data Flow

### Market tick (Phase 0–1)

```
1. KrakenFeed._stream()
   └─ websockets.connect("wss://ws.kraken.com/v2")
   └─ subscribe({"method":"subscribe","params":{"channel":"ticker","symbol":[...]}})

2. KrakenNormalizer.normalize(raw_message)
   └─ produces EventEnvelope(
        event_type = "market.tick",
        event_time = ingest_time = datetime.now(UTC),   ← Kraken has no item timestamp
        payload = { instrument, price, best_bid, best_ask, ... }
      )

3. InProcessBus.publish(envelope)
   ├─ SqliteEventStore.append(envelope)         ← persist FIRST
   └─ asyncio.gather(*[handler(envelope) for handler in subscribers])

4a. PriceAlertGenerator._handle_tick(envelope)
    └─ if 24h cross or % move condition met:
         bus.publish(EventEnvelope(event_type="signal.created", ...))

4b. Broadcaster._fanout(envelope)
    └─ for each connected WebSocket client:
         client.send_text(envelope.model_dump_json())

5. useEventStream (browser)
   └─ JSON.parse(event.data) → EventEnvelope
   └─ dispatch to useMarketTicks  if event_type === "market.tick"
   └─ dispatch to useSignals      if event_type === "signal.created"

6. MarketWatch / SignalFeed re-render with updated data
```

### News signal (Phase 1)

```
1. NewsFeed._fetch(url)
   └─ httpx.AsyncClient.get(url) → response text
   └─ feedparser.parse(text) → feed entries

2. NewsNormalizer.normalize(entry)
   └─ produces EventEnvelope(
        event_type = "signal.created",
        payload = { type="news", title, summary, url, instruments=["BTC-USD",...] }
      )

3. InProcessBus.publish(envelope)   (same persist-first path as ticks)

4. Broadcaster._fanout → browser → useSignals → SignalFeed panel
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
| LLM thesis layer | 2 | Thesis creation, invalidation condition tracking |
| Risk engine | 3 | Deterministic sizing, stop-loss, kill switch |
| Order execution | 4 | Paper trading first, then live via Coinbase Advanced Trade |
| Calibration engine | 5 | ECE measurement, autonomy promotion/demotion |
| Backtest harness | 5 | Replay event stream with mock adapters |
