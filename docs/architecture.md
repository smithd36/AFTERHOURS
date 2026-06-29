# Architecture

> Part of the AFTERHOURS documentation set - see [`README.md`](README.md) for the index and current
> project stage.

AFTERHOURS is a **modular monolith** - all subsystems run in one process, communicate through an in-memory event bus, and share a single SQLite database. The architecture is designed to extract individual subsystems to separate services when throughput or isolation demands it, without changing the application-level contract.

---

## Component Overview

### `core/`

The shared kernel. No dependency on any subsystem.

| Module | Responsibility |
|---|---|
| `core/schemas/common.py` | `Instrument`, `Provenance`, `Money` - canonical domain types |
| `core/schemas/signal.py` | `Signal` (provenance-tagged, payload marked untrusted), `Thesis` |
| `core/schemas/decision.py` | `Decision` and all sub-objects - the central artifact |
| `core/schemas/events.py` | `EventEnvelope`, `EventType` enum (34 topics incl. `watchlist.*`), `AutonomyMode` |
| `core/bus/` | `Bus` ABC, `InProcessBus`, `EventStore` protocol, adapters |
| `core/db/` | aiosqlite connection factory, migration runner |
| `core/mode.py` | `ModeController` - single source of truth for the autonomy mode. Every subsystem reads `current` at point of use instead of caching its own copy (was previously cached in four places), so a dropped/reordered `system.mode_changed` event can't leave subsystems in disagreement. `set()` validates transitions; `halt()` is the kill switch (forces OBSERVE, bypasses validation). Mode is deliberately not persisted - every restart begins in OBSERVE (ADR-004) |
| `core/pricing.py` | `quantize_price()` - rounds to a fixed number of significant figures so the effective tick scales with price. A single hard-coded cent quantum would collapse sub-cent instruments (SHIB/PEPE) to `0.00`; significant-figure rounding never sends a non-zero price to zero |
| `core/logging.py` | structlog with stdlib bridge, dev + JSON render modes |

### `watchlist/`

User-managed instrument registry. Postgres-ready via the `WatchlistStore` protocol pattern.

| Module | Responsibility |
|---|---|
| `watchlist/store.py` | `WatchlistStore` protocol + `SqliteWatchlistStore` - `add(instrument, market)`, `remove(instrument)`, `list_active() -> list[WatchlistEntry]`. All raw SQL confined here; `PostgresWatchlistStore` is a future drop-in |
| `watchlist/manager.py` | `WatchlistManager` - loads store on startup, seeds defaults on first run, exposes `active_instruments: frozenset[str]`, publishes `watchlist.instrument_added` / `watchlist.instrument_removed` onto the bus |
| `watchlist/settings.py` | `WATCHLIST_DEFAULT_INSTRUMENTS` (comma-separated), `WATCHLIST_DEFAULT_MARKET` |

### `ingestion/`

Market data feeds and signal generators. Feeds run as long-lived async tasks; signal generators subscribe to the bus and react to events.

| Module | Responsibility |
|---|---|
| `ingestion/kraken/feed.py` | **Primary crypto feed.** Kraken WebSocket v2, no auth required, tenacity reconnect. Supports dynamic `subscribe(instrument)` / `unsubscribe(instrument)` at runtime - no reconnect needed (Kraken v2 WS supports channel management on live connections) |
| `ingestion/kraken/normalizer.py` | Raw Kraken messages → `EventEnvelope(MARKET_TICK)`. Normalises `BTC/USD` → `BTC-USD`. |
| `ingestion/kraken/settings.py` | `KRAKEN_WS_URL`, `KRAKEN_PRODUCTS` env config (Phase 5: FeedRouter owns runtime subscriptions; static products list used only for testing) |
| `ingestion/equity/feed.py` | **Equity stub feed.** REST polling (Alpaca Data API v2 or Polygon.io free tier) once per `EQUITY_POLL_INTERVAL_SECONDS`. Produces the same `market.tick` envelope as KrakenFeed. Runs in no-op mode when `EQUITY_FEED_API_KEY` is unset - subscriptions still tracked |
| `ingestion/equity/settings.py` | `EQUITY_FEED_PROVIDER`, `EQUITY_FEED_API_KEY`, `EQUITY_FEED_API_SECRET`, `EQUITY_POLL_INTERVAL_SECONDS` |
| `ingestion/router.py` | `FeedRouter` - subscribes to `watchlist.instrument_added/removed`; routes each instrument to `KrakenFeed` (crypto) or `EquityFeed` (equity); bootstraps by subscribing all currently active instruments on startup |
| `ingestion/pruner.py` | `TickPruner` - background task; deletes `market.tick` events older than `TICK_RETENTION_DAYS` every `TICK_PRUNE_INTERVAL_HOURS`; keeps SQLite growth bounded for large watchlists |
| `ingestion/coinbase/feed.py` | **Secondary data feed only.** Coinbase Advanced Trade WebSocket (requires JWT auth - deferred to Phase 7). Not an execution venue: live execution is Alpaca + Kraken (ADR-009). |
| `ingestion/coinbase/normalizer.py` | Raw Coinbase messages → `EventEnvelope(MARKET_TICK)` |
| `ingestion/coinbase/settings.py` | `COINBASE_WS_URL`, `COINBASE_PRODUCTS`, `COINBASE_API_KEY` env config |
| `ingestion/alerts/generator.py` | Subscribes to `market.tick`; emits `signal.created` for 24h crosses and short-window % moves; watchlist-gated |
| `ingestion/alerts/settings.py` | `ALERT_PRICE_MOVE_PCT_THRESHOLD`, `ALERT_COOLDOWN_MINUTES` env config |
| `ingestion/news/feed.py` | Polls RSS feeds (CoinDesk, CoinTelegraph) every 5 min; watchlist-filtered (skips instruments not in active watchlist; general market news passes through when watchlist is non-empty; all suppressed when watchlist is empty) |
| `ingestion/news/normalizer.py` | RSS entry → `EventEnvelope(SIGNAL_CREATED)`. Instrument extraction: prose-name map (all crypto + curated high-profile equity brands) plus live-watchlist equity tickers matched as `$cashtags` / all-caps tokens (case-sensitive, so lowercase prose never tags a ticker) |
| `ingestion/news/settings.py` | `NEWS_FEED_URLS`, `NEWS_POLL_INTERVAL_SECONDS` env config |
| `ingestion/insider/` | **Alt-data (Phase 6A).** SEC EDGAR Form 4 insider transactions → `signal.created` (`insider_tx`). Free, ≤2-day disclosure; disclosure-date `event_time` (two-clock). A core 6B discovery substrate (ADR-012): one of several disclosure sources the Discovery Engine fuses by confluence |
| `ingestion/govexposure/` | **Alt-data (Phase 6A).** Senate LDA lobbying + USASpending federal contracts, bundled as one government-exposure feed → `signal.created` (`lobbying`, `gov_contract`) |
| `ingestion/supplychain/` | **Alt-data (Phase 6A).** 10-K customer-concentration ("Customer X = N% of revenue") dependency disclosures → `signal.created` (`supply_chain`) |
| `ingestion/congress/` | **Alt-data (Phase 6A - built but dormant).** Quiver STOCK Act / congressional disclosures (`congressional_tx`); inert without a free Quiver token. See `docs/phase-6a-limitations.md` |

### `reasoning/`

LLM thesis layer. Converts accumulated signals into structured trade theses via an LLM call, then tracks their validity over time.

| Module | Responsibility |
|---|---|
| `reasoning/llm/base.py` | `LLMProvider` ABC - `async complete(messages) -> str` |
| `reasoning/llm/settings.py` | `LLMSettings` - provider, model, API keys, per-provider defaults |
| `reasoning/llm/__init__.py` | `create_provider()` factory - validates key presence, selects implementation |
| `reasoning/llm/providers/anthropic.py` | Anthropic Claude via `anthropic` SDK |
| `reasoning/llm/providers/openai.py` | OpenAI via `openai` SDK |
| `reasoning/llm/providers/ollama.py` | Local Ollama via `httpx` (no extra dep) |
| `reasoning/llm/providers/openai_compatible.py` | Generic OpenAI-compatible: Groq, Mistral, OpenRouter |
| `reasoning/thesis/generator.py` | Subscribes to `signal.created`; buffers per-instrument; calls LLM; emits `thesis.created`; watchlist-gated |
| `reasoning/thesis/invalidator.py` | Subscribes to `thesis.created`; emits `thesis.invalidated` when time horizon elapses |
| `reasoning/thesis/prompt.py` | Prompt templates - system message + JSON schema instruction |
| `reasoning/thesis/settings.py` | `ThesisSettings` - trigger threshold, window, cooldown, expiry, max tokens |
| `reasoning/decision/generator.py` | Subscribes to `thesis.created`; calls LLM for a trade proposal; emits `decision.proposed` with `prompt_hash`, evidence, ModelInfo. `size_usd` is always `0` here - the risk engine sets it. Watchlist-gated. |
| `reasoning/decision/prompt.py` | Decision prompt templates |
| `reasoning/decision/settings.py` | `DecisionSettings` - max tokens |

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
| `risk/engine.py` | Pre-trade checks (mode via `ModeController`, position limits, no-pyramiding, daily-loss circuit breaker keyed on UTC-day rollover, affordability vs available cash), deterministic sizing, mandatory stop price (a proposal with no computable stop is rejected `no_stop_price` rather than opening an unprotected position); emits `decision.approved`/`decision.rejected`. Watches ticks for stop-loss breaches → `risk.limit_breached`. `evaluate()` is injected into the executor so parked ASSISTED decisions are re-validated at execute time |
| `risk/sizing.py` | `deterministic_size()` - position size from portfolio value + loss limits |
| `risk/settings.py` | `RISK_MAX_POSITION_PCT`, `RISK_MAX_TRADE_LOSS_PCT`, `RISK_STOP_LOSS_PCT`, `RISK_MAX_OPEN_POSITIONS`, `RISK_MAX_DAILY_LOSS_PCT` |

In OBSERVE mode every proposal is rejected with a `shadow decision` reason - logged for calibration, never executed.

### `portfolio/`

Paper trading ledger and execution.

| Module | Responsibility |
|---|---|
| `portfolio/ledger.py` | `Portfolio` - positions, cash, realized/unrealized P&L marked against live ticks; emits `portfolio.position_updated`. Realized P&L factors in **both** entry and exit fees (entry fee stored on `Position` at open); short positions contribute `margin + unrealized_pnl` to equity (not raw market value); `rehydrate()` replays `order.filled` history on startup so a restart restores cash/positions instead of resetting to `initial_cash` |
| `portfolio/executor.py` | `PaperExecutor` - simulated fills with slippage + fees. PAPER mode auto-fills `decision.approved`; ASSISTED mode parks decisions (TTL `PORTFOLIO_PENDING_TTL_SECONDS`, default 1h) until the operator executes/rejects via the API; on TTL expiry, demotion, or halt, parked decisions are flushed with audited `decision.expired` events. Public `reject(decision_id, reason)` emits an audited `decision.rejected`. Each order carries a deterministic `client_order_id` (`<decision_id>:open|close`) so a re-delivered approval or re-fired stop can't double-fill. Closes positions on `risk.limit_breached` |
| `portfolio/models.py` | `Position` (with stored `entry_fee`), `Order` (with `client_order_id`), and snapshot models |
| `portfolio/settings.py` | `PORTFOLIO_INITIAL_CASH`, `PORTFOLIO_SLIPPAGE_PCT`, `PORTFOLIO_FEE_PCT` |

### `analytics/`

Phase 4+ (ADR-011): the **economic** half of the two-gate split - risk/return measurement, kept separate from confidence calibration. Pure, stateless functions plus an on-demand equity-curve projection; no state on `app.state`, no new event type. The economic gate (`calibration/gates.py`) and the portfolio panel both consume `economic_metrics` from here.

| Module | Responsibility |
|---|---|
| `analytics/metrics.py` | Pure risk/return functions over a return series - `sharpe`, `sortino`, `volatility`, `historical_var`, `equity_drawdown` - plus `economic_metrics` (expectancy/win-rate/profit-factor/drawdown on the realized-trade curve, moved here from `calibration/gates.py`). Calendar-daily series (24/7 crypto + equities), so annualization uses **365**, not 252 |
| `analytics/equity_curve.py` | `build_equity_curve` - mark-to-market daily equity as a read-side projection: replays `order.filled` through the *same* `Portfolio` ledger math + marks open positions at each day's last `market.tick`. Event-time keyed, so it reproduces under backtest replay (ADR-011) |
| `analytics/pnl.py` | `realized_pnl` - fill-pairing P&L reconstruction (open→close), extracted so the `/trades` route, the equity curve, and future backtest attribution share one formula |

### `calibration/`

Phase 4: outcome resolution and the calibration north-star metric (PLANNING §1.5). Everything here is driven by tick `event_time`, never the wall clock, so the same components run identically live and in backtest replay.

| Module | Responsibility |
|---|---|
| `calibration/resolver.py` | `OutcomeResolver` - tracks every `decision.proposed` (shadow decisions included) until its time horizon elapses, its stop is breached, or its thesis is invalidated; emits `decision.resolved` with entry/resolution prices, side-adjusted return, and hit/miss. Rehydrates unresolved decisions from the event store on restart and catches up against recent tick history |
| `calibration/engine.py` | `CalibrationEngine` - reliability table (confidence buckets vs hit rate) and ECE, overall and segmented by autonomy mode at proposal time |
| `calibration/gates.py` | `GateTracker` - evaluates the measurable Appendix B graduation criteria (sample size, ECE, span, limit breaches); unmeasurable criteria are reported as deferred, never silently passed |
| `calibration/settings.py` | `CALIBRATION_*` - horizon durations, ECE buckets, gate thresholds |

### `discovery/`

Phase 6B (ADR-012): multi-source opportunity surfacing - fuse weak signals across sources into ranked, explained candidates of *unwatched* instruments worth investigating earlier than standard tools. **Pull-first**: the score is a read-side projection over persisted `signal.created` events (the ADR-011 equity-curve pattern), not a bus subscriber, so it adds no event type and no stateful state. **6B.1 shipped (disclosure-driven, equity-primary); 6B.2 (breadth scanner, crypto-primary, auto-add) is pending.** Depends on `core/` and the `reasoning.llm` abstraction (the analyst); the scoring core stays core-only.

| Module | Responsibility |
|---|---|
| `discovery/extract.py` + `resolve.py` | Map a persisted `signal.created` into signed, factor-tagged Contributions; resolve to a canonical instrument key (drop-on-ambiguous) |
| `discovery/score.py` | The confluence accumulator - **max within a factor** (correlated sources don't double-count) → **noisy-OR across factors** (distinct evidence compounds) + confluence bonus, per-source time-decay; bearish evidence subtracts |
| `discovery/engine.py` | `build_candidates` - the on-demand projection: replays the lookback window, excludes watched instruments, ranks top-k ≥ threshold |
| `discovery/analyst.py` | `AIAnalyst` - lazy, operator-triggered LLM pass over one candidate (why-interesting + counter-signals; explains, never decides). Reuses the shared `reasoning.llm` provider, so cache + throttle apply |
| `discovery/settings.py` | `DISCOVERY_*` - window, threshold, top-k, confluence bonus, per-factor weight/half-life defaults, analyst token cap |

### `gateway/`

The FastAPI application. Exposes HTTP endpoints and the WebSocket feed. Manages the application lifespan.

| Module | Responsibility |
|---|---|
| `gateway/app.py` | `create_app()` factory, `default_lifespan`, health/status/WS routes |
| `gateway/broadcaster.py` | `Broadcaster` - subscribes to bus, fans out to WS clients. Each client has its own bounded outbound queue (`WS_CLIENT_QUEUE_SIZE`) drained by a dedicated writer task; a slow client drops its own oldest messages rather than back-pressuring the bus (and thus the Kraken dispatch loop / risk tick path). `total_dropped` is surfaced on `GET /api/status` |
| `gateway/routes/mode.py` | `GET/POST /api/mode` - reads/sets the shared `ModeController`; transitions validated by the controller (single source of truth, updated before the audit event is published) |
| `gateway/routes/decisions.py` | `GET /api/decisions`, `GET /api/decisions/pending`, `POST /api/decisions/{id}/execute|reject` (Assisted-mode operator actions) |
| `gateway/routes/portfolio.py` | `GET /api/portfolio`, `POST /api/portfolio/positions/{instrument}/close` |
| `gateway/routes/halt.py` | `POST /api/halt` - kill switch; calls `ModeController.halt()` (forces OBSERVE, emits `risk.halt`), which flushes the executor's pending queue with audited `decision.expired` events |
| `gateway/routes/events.py` | `GET /api/events/recent` - recent events from the audit log for UI panel rehydration |
| `gateway/routes/calibration.py` | `GET /api/calibration` (ECE + reliability), `GET /api/calibration/gates` (Appendix B readiness) |
| `gateway/routes/analytics.py` | `GET /api/analytics` - equity curve + Sharpe/Sortino/volatility/VaR + equity-curve drawdown (on-demand projection; Sharpe is informational, not a gate criterion - ADR-011) |
| `gateway/routes/watchlist.py` | `GET /api/watchlist`, `POST /api/watchlist` (add instrument), `DELETE /api/watchlist/{instrument}` (remove) |
| `gateway/routes/discovery.py` | `GET /api/discovery` (ranked candidate feed - on-demand projection), `GET /api/discovery/{instrument}/analysis` (lazy AI analyst pass) |
| `gateway/settings.py` | `HOST`, `PORT`, `CORS_ORIGINS` env config |

### `frontend/`

React terminal UI built with Vite, TypeScript, Tailwind CSS v4, and shadcn/ui (new-york style, zinc base).

| Module | Responsibility |
|---|---|
| `hooks/useEventStream.ts` | WS connection to `/ws`, exponential backoff reconnect |
| `hooks/useBackfill.ts` | On mount, fetches `/api/events/recent` and replays history through the same reducers as live events |
| `hooks/useMarketTicks.ts` | `useReducer`-backed tick map; dispatches on `market.tick`; purges instrument on `watchlist.instrument_removed` |
| `hooks/useSignals.ts` | Accumulates last 50 `signal.created` events; deduplicates by id; watchlist-filtered - purges on removal, backfills on add, empty watchlist suppresses all signals |
| `hooks/useTheses.ts` | Accumulates last 20 `thesis.created`; updates status on `thesis.invalidated`; watchlist-filtered with same add/remove sync as signals |
| `hooks/useDecisions.ts` | Decision rows keyed by id; status updated by `decision.approved`/`decision.rejected`; watchlist-filtered with same add/remove sync |
| `hooks/usePortfolio.ts` | Portfolio snapshot from `/api/portfolio` + `portfolio.position_updated` events |
| `hooks/useCalibration.ts` | Calibration + gate reports from `/api/calibration*`, refetched (debounced) on `decision.resolved` / `risk.limit_breached` |
| `hooks/useAnalytics.ts` | Equity curve + risk/return metrics from `/api/analytics`, fetched on mount and refetched (debounced) on `order.filled` |
| `hooks/useWatchlist.ts` | REST snapshot on mount + live updates from `watchlist.*` WS events; exposes `add`/`remove` mutations |
| `hooks/useDiscovery.ts` | Pull-first: fetches `/api/discovery` on mount + manual refresh (no event stream in the 6B.1 MVP); per-candidate AI analysis fetched lazily on demand |
| `components/panels/MarketWatch.tsx` | Live tick table with bullish/bearish price colouring |
| `components/panels/SignalFeed.tsx` | Scrollable signal list; PRICE/NEWS badges; relative-age labels |
| `components/panels/ThesisFeed.tsx` | Thesis cards; LONG/SHORT/NEUTRAL + ACTIVE/EXPIRED/INVALIDATED badges; invalidation conditions |
| `components/panels/DecisionQueue.tsx` | Decision cards with risk verdict; EXECUTE/REJECT buttons in Assisted mode |
| `components/panels/PortfolioPanel.tsx` | Cash, positions, unrealized P&L |
| `components/panels/CalibrationPanel.tsx` | Headline ECE, reliability bars (hit rate vs stated confidence), Appendix B gate readiness |
| `components/panels/AnalyticsPanel.tsx` | Equity curve + risk/return metrics (Sharpe/Sortino/volatility/VaR, drawdown, net P&L) - the economic gate's read-side view |
| `components/panels/WatchlistPanel.tsx` | Add/remove instruments at runtime; crypto/equity market selector; filter-as-you-type search (shown when >3 entries); per-instrument live feed-status dot (green = receiving ticks, dim = waiting) |
| `components/panels/DiscoveryFeed.tsx` | Ranked discovery candidates: score bar + factor chips, expandable evidence (signed contributions), one-click add-to-watchlist, and a lazy "Analyze with AI" pass (thesis + counter-signals) |
| `components/layout/PanelShell.tsx` | Reusable terminal panel (header bar + content slot) |
| `types/core.ts` | TypeScript mirror of `core/schemas/*.py` |

The panels are grouped into three workflow **workspaces** switched from the header (and, on mobile, a workspace-scoped bottom tab bar): **Discover** (the pre-watchlist funnel - candidate feed + watchlist curation), **Terminal** (the live pipeline - markets/signals/theses/decisions), and **Review** (outcomes - portfolio/calibration/analytics). The header bar carries the OBSERVE/PAPER/ASSISTED mode switch (`/api/mode`) and the HALT kill switch (`/api/halt`).

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

#### Risk-limit gate semantics

The `risk.limit_breached` event is overloaded. Today it is emitted from exactly one place - the stop-loss monitor (`risk/engine.py`, `reason: "stop_loss"`) - which is *normal contained-loss behaviour*, not a violation of the system's hard caps. The genuine hard limits (max open positions, no-pyramiding, daily-loss circuit breaker, affordability) are enforced **pre-trade** and surface as `decision.rejected`; they can never produce a `risk.limit_breached` event because the position is never opened.

The Paper → Assisted graduation gate (`calibration/gates.py`, Appendix B "zero risk-limit breaches") therefore counts only *hard* breaches and **excludes stop-loss closes** (`_is_hard_breach`). Without this, any realistic paper run - which inevitably takes losing trades that hit their stops - would keep the gate at "not ready" forever, treating the safety mechanism doing its job as evidence against graduation. As wired, the deferred consequence is that the counter currently has no event that can ever increment it (all true hard-limit conditions are prevented pre-trade), so the criterion reads 0 by construction.

**Option B (deferred):** split the event - emit a distinct `risk.stop_triggered` for stop-loss closes and reserve `risk.limit_breached` for genuine post-fill cap violations (e.g. if a future limit can be breached *after* a position is open: a trailing exposure cap, a portfolio-level drawdown halt, a reconciliation mismatch). At that point the reason-string filter is no longer sufficient and the two concepts deserve separate event types. This touches the `EventType` enum, the executor's `risk.limit_breached` subscription (which closes positions), the frontend `core.ts` union, and `useCalibration` refetch triggers - hence deferred until a real post-fill limit exists to justify it. Until then, the reason filter is the lazy correct behaviour.

### Outcome resolution (Phase 4)

```
6. OutcomeResolver (subscribes to decision.proposed, decision.approved,
   market.tick, thesis.invalidated)
   ├─ entry price = first tick with event_time ≥ proposal
   ├─ tick event_time passes the horizon deadline → decision.resolved
   │    (reason horizon_elapsed; stop breach / thesis invalidation resolve early)
   └─ payload: predicted_side, confidence, mode_at_proposal, entry/resolution
        prices, side-adjusted realized_return_pct, hit

7. CalibrationEngine (subscribes to decision.resolved)
   └─ reliability buckets + ECE → GET /api/calibration
      GateTracker → Appendix B readiness → GET /api/calibration/gates
```

Shadow decisions (OBSERVE-mode rejections) are resolved like any other - they are the Observe → Paper gate sample. Resolution is driven entirely by tick `event_time`, so restarts catch up by replaying stored history, and the backtest engine reuses the resolver unchanged.

### Backtest replay (Phase 4)

```
python -m backtest --from 2026-06-01 --to 2026-06-08 [--llm replay|live]

1. SqliteEventStore.range(["market.tick","signal.created"], start, end)
   └─ chronological source events from afterhours.db

2. BacktestRunner.run()
   └─ isolated InMemoryEventStore + InProcessBus
   └─ same pipeline as live: ThesisGenerator → DecisionGenerator →
      RiskEngine → PaperExecutor → Portfolio → OutcomeResolver → CalibrationEngine
   └─ each source event published in order; derived events regenerate naturally

3. LLM calls → CachingProvider
   ├─ replay mode (default): serve recorded responses keyed by prompt_hash; miss → skip
   └─ live mode: call provider, record response for future replays

4. write_artifact(report, "backtest_runs/")
   └─ JSON: run_id, window, replayed counts, generated counts,
      calibration report, equity curve, portfolio snapshot, settings
```

Point-in-time correctness: every financial decision uses the triggering event's `event_time`; no component calls `datetime.now()` in a financial path during replay.

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
- `event_time DESC` - timeline view
- `(event_type, event_time DESC)` - per-topic queries
- `correlation_id WHERE NOT NULL` - full decision lifecycle reconstruction

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
| `decision` | `proposed`, `approved`, `rejected`, `expired`, `executing`, `executed`, `failed`, `resolved` |
| `order` | `submitted`, `filled`, `partially_filled`, `cancelled`, `failed` |
| `portfolio` | `position_updated`, `reconciled`, `reconciliation_failed` |
| `risk` | `limit_approached`, `limit_breached`, `halt` |
| `system` | `feed_healthy`, `feed_degraded`, `feed_dead`, `mode_changed`, `error` |
| `watchlist` | `instrument_added`, `instrument_removed` |

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

Confusing them is a source of look-ahead bias. The rule is enforced by naming - application code that uses `ingest_time` for financial decisions is a bug.

---

## The Decision Object

`Decision` is the load-bearing domain object. Every trade recommendation is a `Decision` instance that lives immutably once created. Status transitions are new events, not mutations.

```
Decision
├── id                      UUID - also the correlation_id for all lifecycle events
├── originating_thesis_id   which Thesis triggered this (nullable)
├── input_signal_ids        point-in-time snapshot - enables deterministic audit replay
├── model: ModelInfo
│   └── prompt_hash         sha256 of fully-rendered prompt - locks reasoning to exact call
├── proposal: Proposal
│   └── size_usd            set by sizing code, NEVER by the LLM
├── reasoning               LLM-generated
├── evidence[]              each item cites a real Signal.id
├── confidence              0–1
├── risk: RiskAssessment
│   └── risk_engine_verdict  authoritative - overrides LLM confidence
├── status                  proposed → approved/rejected → executing → executed/failed
├── human: HumanAction      approval, rejection, or edit record
└── outcome: DecisionOutcome fills, realised P&L, slippage
```

**Separation of duties enforced in the schema:** the LLM's contribution is scoped to `reasoning`, `evidence[]`, `confidence`, and the directional elements of `Proposal`. Size is computed deterministically. Risk verdict is computed deterministically. The LLM cannot unilaterally commit capital.

---

## Frontend Design System

| Token | Value | Semantic meaning |
|---|---|---|
| `--bullish` | `oklch(0.65 0.18 145)` | green - positive price change |
| `--bearish` | `oklch(0.55 0.22 27)` | red - negative price change |
| `--warning` | `oklch(0.75 0.18 85)` | amber - degraded feed, caution |
| `--info` | `oklch(0.65 0.14 240)` | blue - informational |
| `--background` | `oklch(0.11 0 0)` | near-black terminal background |

Font stack: Geist Mono → JetBrains Mono → Fira Code → ui-monospace. The terminal is always dark; light mode is not a design target.

---

### `backtest/`

Event-time replay engine. Loads recorded source events from `SqliteEventStore.range()`, wires the full pipeline onto an isolated in-memory bus, and runs it to completion. LLM calls are served from a JSON file cache - deterministic and free on replay runs, recorded on the first live pass.

| Module | Responsibility |
|---|---|
| `backtest/runner.py` | `BacktestRunner` - assembles all pipeline components on a fresh in-memory bus, replays source events, collects generated-event counts, equity curve, calibration report, and portfolio snapshot into a `dict` run artifact |
| `backtest/__main__.py` | CLI entry point (`python -m backtest`): loads events from `afterhours.db`, builds a `CachingProvider`, runs the runner, writes a JSON artifact to `backtest_runs/`, prints a summary |
| `backtest/__init__.py` | Re-exports `BacktestRunner`, `write_artifact` |

Only **source topics** are replayed (`market.tick`, `signal.created`). Derived events (theses, decisions, fills, resolutions) regenerate through the live pipeline - replaying them would double-count. The thesis invalidator is excluded from replay (wall-clock paced); decisions still resolve via their time horizon, so calibration is unaffected. Point-in-time correctness is guaranteed because every pipeline component uses the triggering envelope's `event_time` as its financial clock.

---

## Planned Subsystems (not yet built)

| Subsystem | Phase | Notes |
|---|---|---|
| Discovery breadth scanner + control plane (6B.2) | 6B.2 | Extends the **shipped** 6B.1 discovery (`discovery/`, ADR-012 - see the `discovery/` section above) with a broad-universe scanner (Alpaca screener / CoinGecko volume / Kraken listings) feeding the same projection → unlocks **crypto-primary**; plus the control plane: auto-add with a `source="discovery"` cap + TTL/cooldown, and a liquidity admission floor + ADV-% size cap in the risk engine (which is liquidity-blind today) |
| `BrokerAdapter` + live venues | 7A–7B | Venue-neutral ABC parallel to `PaperExecutor`, sharing the `Order`/`client_order_id` contract. **Alpaca** primary (paper→live parity, equities + crypto) in 7A; **Kraken** live crypto in 7B (ADR-009). Assisted mode only, micro sizes. Staged plan: [`phase-7-plan.md`](phase-7-plan.md) |
| Capital ramp & live semi-auto | 7C–7D | Stepwise size increases gated on clean reconciliation (7C); bounded autonomous execution on the Appendix B Assisted→Semi-auto gate (7D) |
| Scale & autonomy | 8 | Full equities adapter, supervised-auto mode, correlation risk, Strategy Lab; Postgres migration path via `EventStore` / `WatchlistStore` protocol swap |
| Harden & extend | 9 | Performance, service extraction, advanced observability, disaster recovery |
