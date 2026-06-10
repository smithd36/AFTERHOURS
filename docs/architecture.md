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
| `ingestion/coinbase/feed.py` | **Secondary feed.** Coinbase Advanced Trade WebSocket (requires JWT auth — deferred to Phase 5) |
| `ingestion/coinbase/normalizer.py` | Raw Coinbase messages → `EventEnvelope(MARKET_TICK)` |
| `ingestion/coinbase/settings.py` | `COINBASE_WS_URL`, `COINBASE_PRODUCTS`, `COINBASE_API_KEY` env config |
| `ingestion/alerts/generator.py` | Subscribes to `market.tick`; emits `signal.created` for 24h crosses and short-window % moves |
| `ingestion/alerts/settings.py` | `ALERT_PRICE_MOVE_PCT_THRESHOLD`, `ALERT_COOLDOWN_MINUTES` env config |
| `ingestion/news/feed.py` | Polls RSS feeds (CoinDesk, CoinTelegraph) every 5 min. Publishes current headlines on first-ever run; restarts dedupe against the event store |
| `ingestion/news/normalizer.py` | RSS entry → `EventEnvelope(SIGNAL_CREATED)` with keyword-based instrument extraction |
| `ingestion/news/settings.py` | `NEWS_FEED_URLS`, `NEWS_POLL_INTERVAL_SECONDS` env config |

### `reasoning/`

LLM thesis layer. Converts accumulated signals into structured trade theses via an LLM call, then tracks their validity over time.

| Module | Responsibility |
|---|---|
| `reasoning/llm/base.py` | `LLMProvider` ABC — `async complete(messages) -> str` |
| `reasoning/llm/settings.py` | `LLMSettings` — provider, model, API keys, per-provider defaults |
| `reasoning/llm/__init__.py` | `create_provider()` factory — validates key presence, selects implementation |
| `reasoning/llm/providers/anthropic.py` | Anthropic Claude via `anthropic` SDK |
| `reasoning/llm/providers/openai.py` | OpenAI via `openai` SDK |
| `reasoning/llm/providers/ollama.py` | Local Ollama via `httpx` (no extra dep) |
| `reasoning/llm/providers/openai_compatible.py` | Generic OpenAI-compatible: Groq, Mistral, OpenRouter |
| `reasoning/thesis/generator.py` | Subscribes to `signal.created`; buffers per-instrument; calls LLM; emits `thesis.created` |
| `reasoning/thesis/invalidator.py` | Subscribes to `thesis.created`; emits `thesis.invalidated` when time horizon elapses |
| `reasoning/thesis/prompt.py` | Prompt templates — system message + JSON schema instruction |
| `reasoning/thesis/settings.py` | `ThesisSettings` — trigger threshold, window, cooldown, expiry, max tokens |
| `reasoning/decision/generator.py` | Subscribes to `thesis.created`; calls LLM for a trade proposal; emits `decision.proposed` with `prompt_hash`, evidence, ModelInfo. `size_usd` is always `0` here — the risk engine sets it. |
| `reasoning/decision/prompt.py` | Decision prompt templates |
| `reasoning/decision/settings.py` | `DecisionSettings` — max tokens |

**Supported providers:**

| `LLM_PROVIDER` | Cost | Default model |
|---|---|---|
| `ollama` | Free (local) | `llama3.2` |
| `groq` | Free 14k req/day | `llama-3.3-70b-versatile` |
| `mistral` | Free 1B tok/month | `mistral-small-latest` |
| `openrouter` | Free 50 req/day | `llama-3.3-70b-instruct:free` |
| `anthropic` | Paid | `claude-haiku-4-5-20251001` |
| `openai` | Paid | `gpt-4o-mini` |

### `risk/`

The deterministic gatekeeper. Every `decision.proposed` passes through here before any capital (real or simulated) is committed. The LLM cannot bypass it.

| Module | Responsibility |
|---|---|
| `risk/engine.py` | Pre-trade checks (mode, position limits, daily-loss circuit breaker), deterministic sizing, stop price; emits `decision.approved`/`decision.rejected`. Watches ticks for stop-loss breaches → `risk.limit_breached` |
| `risk/sizing.py` | `deterministic_size()` — position size from portfolio value + loss limits |
| `risk/settings.py` | `RISK_MAX_POSITION_PCT`, `RISK_MAX_TRADE_LOSS_PCT`, `RISK_STOP_LOSS_PCT`, `RISK_MAX_OPEN_POSITIONS`, `RISK_MAX_DAILY_LOSS_PCT` |

In OBSERVE mode every proposal is rejected with a `shadow decision` reason — logged for calibration, never executed.

### `portfolio/`

Paper trading ledger and execution.

| Module | Responsibility |
|---|---|
| `portfolio/ledger.py` | `Portfolio` — positions, cash, realized/unrealized P&L marked against live ticks; emits `portfolio.position_updated` |
| `portfolio/executor.py` | `PaperExecutor` — simulated fills with slippage + fees. PAPER mode auto-fills `decision.approved`; ASSISTED mode parks decisions until the operator executes/rejects via the API. Closes positions on `risk.limit_breached` |
| `portfolio/models.py` | Position and snapshot models |
| `portfolio/settings.py` | `PORTFOLIO_INITIAL_CASH`, `PORTFOLIO_SLIPPAGE_PCT`, `PORTFOLIO_FEE_PCT` |

### `gateway/`

The FastAPI application. Exposes HTTP endpoints and the WebSocket feed. Manages the application lifespan.

| Module | Responsibility |
|---|---|
| `gateway/app.py` | `create_app()` factory, `default_lifespan`, health/status/WS routes |
| `gateway/broadcaster.py` | `Broadcaster` — subscribes to bus, fans out to WS clients |
| `gateway/routes/mode.py` | `GET/POST /api/mode` — autonomy mode with validated transitions |
| `gateway/routes/decisions.py` | `GET /api/decisions`, `GET /api/decisions/pending`, `POST /api/decisions/{id}/execute|reject` (Assisted-mode operator actions) |
| `gateway/routes/portfolio.py` | `GET /api/portfolio`, `POST /api/portfolio/positions/{instrument}/close` |
| `gateway/routes/halt.py` | `POST /api/halt` — kill switch; emits `risk.halt` and forces OBSERVE |
| `gateway/routes/events.py` | `GET /api/events/recent` — recent events from the audit log for UI panel rehydration |
| `gateway/settings.py` | `HOST`, `PORT`, `CORS_ORIGINS` env config |

### `frontend/`

React terminal UI built with Vite, TypeScript, Tailwind CSS v4, and shadcn/ui (new-york style, zinc base).

| Module | Responsibility |
|---|---|
| `hooks/useEventStream.ts` | WS connection to `/ws`, exponential backoff reconnect |
| `hooks/useBackfill.ts` | On mount, fetches `/api/events/recent` and replays history through the same reducers as live events |
| `hooks/useMarketTicks.ts` | `useReducer`-backed tick map; dispatches on `market.tick` |
| `hooks/useSignals.ts` | Accumulates last 50 `signal.created` events; deduplicates by id |
| `hooks/useTheses.ts` | Accumulates last 20 `thesis.created`; updates status on `thesis.invalidated` |
| `hooks/useDecisions.ts` | Decision rows keyed by id; status updated by `decision.approved`/`decision.rejected` |
| `hooks/usePortfolio.ts` | Portfolio snapshot from `/api/portfolio` + `portfolio.position_updated` events |
| `components/panels/MarketWatch.tsx` | Live tick table with bullish/bearish price colouring |
| `components/panels/SignalFeed.tsx` | Scrollable signal list; PRICE/NEWS badges; relative-age labels |
| `components/panels/ThesisFeed.tsx` | Thesis cards; LONG/SHORT/NEUTRAL + ACTIVE/EXPIRED/INVALIDATED badges; invalidation conditions |
| `components/panels/DecisionQueue.tsx` | Decision cards with risk verdict; EXECUTE/REJECT buttons in Assisted mode |
| `components/panels/PortfolioPanel.tsx` | Cash, positions, unrealized P&L |
| `components/layout/PanelShell.tsx` | Reusable terminal panel (header bar + content slot) |
| `types/core.ts` | TypeScript mirror of `core/schemas/*.py` |

The header bar carries the OBSERVE/PAPER/ASSISTED mode switch (`/api/mode`) and the HALT kill switch (`/api/halt`).

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

### Decision pipeline (Phase 3)

```
1. ThesisGenerator
   └─ ≥ THESIS_MIN_SIGNALS_TO_TRIGGER signals for one instrument within the
      window → LLM call → thesis.created

2. DecisionGenerator._handle_thesis(envelope)
   └─ LLM call → decision.proposed
      (size_usd = 0; prompt_hash = sha256 of the rendered prompt)

3. RiskEngine._handle_proposed(envelope)
   ├─ OBSERVE mode        → decision.rejected ("shadow decision")
   ├─ limit breach        → decision.rejected (reasons in risk.rejection_reasons)
   └─ otherwise           → deterministic size + stop price → decision.approved

4. PaperExecutor._handle_approved(envelope)
   ├─ PAPER mode          → simulated fill (slippage + fee) → order.filled
   └─ ASSISTED mode       → parked in pending queue
        └─ operator POST /api/decisions/{id}/execute → order.filled

5. Portfolio (subscribes to order.filled, market.tick)
   └─ positions, cash, P&L → portfolio.position_updated → PortfolioPanel
```

Stop-loss: the risk engine watches every tick against open positions' stop prices; a breach emits `risk.limit_breached` and the executor closes the position.

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
| Outcome resolution | 4 | Score decisions against realized price action at their time horizon (`decision.resolved`) |
| Backtest harness | 4 | Point-in-time correct event replay with mock adapters |
| Calibration engine | 4 | ECE measurement, autonomy gate tracking (Appendix B) |
| Live exchange adapter | 5 | Assisted mode only, micro sizes; execution venue re-confirmed at phase start (ADR-007) |
| Scale & autonomy | 6 | Equities, semi-auto mode, correlation risk, Strategy Lab |
| Harden & extend | 7 | Performance, service extraction, advanced observability, disaster recovery |

Phase 4 implementation plan: [`docs/phase4-plan.md`](phase4-plan.md).
