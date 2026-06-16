# AFTERHOURS

> AI-assisted trading terminal for single-operator, own-capital use.

A modular monolith that connects live market data, LLM-generated trade theses, a deterministic risk engine, and a real-time browser terminal — with graduated human oversight at every level of autonomy.

---

## Status

**Phase 6A complete (2026-06-15); Phase 6B (auto-discovery) next; live trading is Phase 7 (staged 7A–7D), per [ADR-010](docs/adr/010-roadmap-rescope-alt-data-phase6.md).** 6A shipped three free alt-data feeds live — insider (SEC Form 4), government-exposure (lobbying + contracts), and supply-chain (10-K) — all enrich-only into the existing pipeline; congress is built but dormant (no free token) and dark-pool/options is deferred (paid). See [`docs/phase-6a-limitations.md`](docs/phase-6a-limitations.md). Full decision pipeline live end-to-end, with user-managed watchlist, dynamic feed routing across crypto and equity, watchlist-scoped pipeline filtering, and tick retention:

```
Kraken WebSocket ─┐
EquityFeed (REST) ─┤─ FeedRouter ─── InProcessBus ── SQLiteEventStore ── FastAPI /ws + /api ── React terminal
RSS News Feed    ─┘        ↑
                     WatchlistManager (persist + seed defaults → watchlist.instrument_added/removed)
                            │
              PriceAlertGenerator  (ticks → signal.created, watchlist-filtered)
              NewsFeed             (CoinDesk / CoinTelegraph → signal.created, watchlist-filtered)
              ThesisGenerator      (signals → LLM → thesis.created, watchlist-filtered)
              ThesisInvalidator    (time horizon elapsed → thesis.invalidated)
              DecisionGenerator    (theses → LLM → decision.proposed, watchlist-filtered)
              RiskEngine           (deterministic sizing/limits → decision.approved/rejected)
              PaperExecutor        (simulated fills → order.filled)
              Portfolio            (positions, cash, P&L → portfolio.position_updated)
              OutcomeResolver      (prediction vs price at horizon → decision.resolved)
              CalibrationEngine    (ECE + Appendix B gate tracking → /api/calibration)
              GateTracker          (Observe → Paper promotion readiness → /api/calibration/gates)
              BacktestRunner       (event-time replay → run artifact → calibration report)
              TickPruner           (background task — bounds SQLite growth for large watchlists)
```

Autonomy modes Observe / Paper / Assisted are operational with a kill-switch HALT,
Decision Queue (operator approve/reject in Assisted mode), portfolio panel,
CalibrationPanel (headline ECE, reliability bars, gate progress), and
WatchlistPanel (add/remove instruments at runtime; live feed-status indicator per instrument).
LLM provider is pluggable: Groq · Mistral · OpenRouter (free) or Anthropic · OpenAI · Ollama.
Backtest CLI: `python -m backtest [--from DATE] [--to DATE] [--llm replay|live]`.

**Pre-Phase-6 hardening (blockers cleared, 2026-06-12):** the paper system has been hardened to
live-trading standards before any real order — a single `ModeController` owns the autonomy mode,
the kill switch expires pending decisions, the portfolio and decision store rehydrate from the
event log on restart, ledger accounting is corrected (entry-fee P&L, short equity, daily-loss
rollover, affordability), decision→order→fill carries a deterministic client order ID, prices
quantize magnitude-aware (sub-cent safe), and LLM output is schema-validated before publish. All
7 CRITICAL phase-6-blocker issues and the IMPORTANT correctness/durability issues are closed; the
one remaining entry gate for Phase 7A (live trading) is a single-operator local gateway bar — bind `127.0.0.1`
(today's `0.0.0.0` default exposes the kill switch to the whole LAN) plus a shared-secret token on
state-changing routes and the WS (full "auth like a bank" deferred to Phase 8+) — plus a few
non-blocking hygiene cleanups. Tracked in [`docs/pre-phase-6-issues.md`](docs/pre-phase-6-issues.md)
(review: `docs/pre-phase6-review.md`).

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+

### 1 — Clone and set up Python environment

```bash
git clone <repo>
cd afterhours

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e ".[dev]"
```

### 2 — Configure environment

```bash
cp .env.example .env
# Edit .env if needed — defaults work for local dev
```

### 3 — Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 4 — Run

Open two terminals.

**Terminal 1 — backend:**
```bash
python -m gateway
```

**Terminal 2 — frontend:**
```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`. The connection indicator goes green and live ticks appear within a few seconds.

### Tests

```bash
pytest
pytest --cov=core --cov=gateway --cov=ingestion   # with coverage
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    AFTERHOURS process                     │
│                                                          │
│  ┌──────────────┐    ┌────────────────┐                  │
│  │  Ingestion   │───▶│  InProcessBus  │◀─── subscribers  │
│  │ (Kraken, RSS)│    │                │                  │
│  └──────────────┘    │  persist-first │                  │
│                      │  then fan-out  │                  │
│  ┌──────────────┐    └───────┬────────┘                  │
│  │  Reasoning   │            │                           │
│  │ (LLM theses  │            ▼                           │
│  │ + decisions) │    ┌─────────────────┐                 │
│  └──────────────┘    │ SqliteEventStore│                 │
│                      │  (events table) │                 │
│  ┌──────────────┐    └─────────────────┘                 │
│  │ Risk Engine  │                                        │
│  └──────────────┘    ┌────────────────┐                  │
│  ┌──────────────┐    │    FastAPI     │                  │
│  │PaperExecutor │    │   /ws  /api    │                  │
│  │ + Portfolio  │    └───────┬────────┘                  │
│  └──────────────┘            │                           │
└──────────────────────────────┼───────────────────────────┘
                               │ WebSocket + REST
                      ┌────────▼────────┐
                      │  React terminal │
                      │  (Vite + TS)    │
                      └─────────────────┘
```

All inter-subsystem communication flows through the event bus as `EventEnvelope` objects. Consumers subscribe by topic prefix (`"market.*"`, `"decision.*"`, `"*"`). The bus persists every event to SQLite before fan-out — the event store is the audit log.

**Diagrams:**
- 📊 [Full event-pipeline diagram](docs/pipeline.svg) — ingestion → thesis → decision → risk → execution, with the event topic on every handoff.
- 🗺️ [Plain-language overview](docs/pipeline-simple.svg) — the same flow, no jargon.

See [`docs/architecture.md`](docs/architecture.md) for the full breakdown and [`docs/adr/`](docs/adr/) for key design decisions.

---

## Directory Structure

```
afterhours/
├── core/                   # Shared domain — schemas, event bus, DB
│   ├── schemas/            # Pydantic models: events, signals, decisions
│   ├── bus/                # InProcessBus, EventStore protocol, adapters
│   ├── db/                 # aiosqlite connection, migration runner
│   ├── mode.py             # ModeController — single source of truth for autonomy mode
│   └── pricing.py          # quantize_price — magnitude-aware (sub-cent safe) rounding
│
├── watchlist/              # Instrument watchlist — WatchlistManager, WatchlistStore protocol
│
├── ingestion/              # Market data feeds and signal generators
│   ├── kraken/             # Kraken WebSocket v2 (primary, no auth; dynamic subscribe/unsubscribe)
│   ├── equity/             # EquityFeed stub — REST polling (Alpaca/Polygon free tier)
│   ├── coinbase/           # Coinbase Advanced Trade (secondary; auth wiring in Phase 7)
│   ├── alerts/             # PriceAlertGenerator — tick → signal.created
│   ├── news/               # RSS feed poller (CoinDesk, CoinTelegraph)
│   ├── router.py           # FeedRouter — maps watchlist add/remove to feed subscriptions
│   └── pruner.py           # TickPruner — background task, bounds tick history growth
│
├── reasoning/              # LLM layer
│   ├── llm/                # LLMProvider ABC + Anthropic/OpenAI/Ollama/compatible providers
│   ├── thesis/             # ThesisGenerator, ThesisInvalidator, prompts
│   └── decision/           # DecisionGenerator — thesis → decision.proposed
│
├── risk/                   # Deterministic risk engine — sizing, limits, stop-loss
├── portfolio/              # Paper trading — ledger, PaperExecutor, fills
├── calibration/            # Outcome resolution, ECE engine, autonomy gate tracking
├── backtest/               # BacktestRunner, write_artifact, CLI (python -m backtest)
│
├── gateway/                # FastAPI app — HTTP + WebSocket gateway
│   └── routes/             # /api/mode, /api/decisions, /api/portfolio, /api/halt, /api/events, /api/calibration, /api/watchlist
│
├── frontend/               # React terminal UI
│   └── src/
│       ├── components/     # MarketWatch, SignalFeed, ThesisFeed, DecisionQueue, PortfolioPanel, CalibrationPanel, WatchlistPanel
│       ├── hooks/          # useEventStream, useBackfill, useSignals, useTheses, useDecisions, useCalibration, useWatchlist, …
│       └── types/          # TypeScript mirror of core/schemas
│
├── tests/                  # pytest test suite
├── docs/                   # Architecture docs, ADRs, dev guide
│
├── PLANNING.md             # Full architecture decisions and phase roadmap
├── .env.example            # Environment variable template
└── pyproject.toml          # Python project config and dependencies
```

---

## Design Principles

**Single-operator, own-capital only.** This system is not a multi-tenant platform. Regulatory and architectural decisions are made for one operator trading their own capital.

**Decision Object as the central artifact.** Every trade recommendation is a `Decision` — immutable, with point-in-time signal references and a `prompt_hash` for audit replay. The LLM proposes direction; a deterministic risk engine sets size and is the final gate.

**Calibration over returns.** The primary metric for autonomy promotion is ECE (Expected Calibration Error), not P&L. A well-calibrated model that says "60% confident" should be right about 60% of the time.

**Autonomy is graduated.** Five modes — Observe → Paper → Assisted → Semi-auto → Supervised — with explicit promotion criteria and automatic demotion triggers. Kill switch available at all times.

**Free data first.** All external data is behind adapters. Kraken WebSocket v2 (no API key needed) is the confirmed primary crypto data source. Equity data uses Alpaca or Polygon free-tier REST polling (`EQUITY_FEED_API_KEY`); without a key the equity feed runs in no-op mode (watchlist management still works). Coinbase stays integrated as the secondary data feed (ADR-007). **Live execution** (Phase 7) uses Alpaca primary + Kraken secondary (ADR-009) — no execution keys needed until Phase 7A.

See [`PLANNING.md`](PLANNING.md) for the full non-negotiables list.

---

## Phase Roadmap

| Phase | Focus | Key Deliverable |
|---|---|---|
| **0** ✅ | Infrastructure | Live ticks end-to-end: exchange → bus → DB → screen |
| **1** ✅ | Signals | Price alerts + RSS news ingestion, SignalFeed panel |
| **2** ✅ | Thesis | Pluggable LLM thesis generation, time-based invalidation, ThesisFeed panel |
| **3** ✅ | Risk + Paper | Decision generator, risk engine, kill switch, paper execution, portfolio/ledger, Decision Queue UI |
| **4** ✅ | Backtest + Calibration | Backtesting engine (event-time replay, no look-ahead), decision outcome resolution, ECE calibration reporting, autonomy gate tracking |
| **5** ✅ | Watchlist & Multi-Instrument | User-managed watchlist, dynamic feed routing (crypto + equity stub), watchlist-scoped pipeline, tick retention, WatchlistPanel |
| **6A** ✅ | Alt-data signal feeds (enrich-only) | Live: insider (Form 4) / lobbying+contracts (gov-exposure) / supply-chain pollers → `signal.created`; materiality filters, disclosure-date `event_time`, thesis-seed trigger; trades watched equities only. Congress built but dormant; options-flow deferred (paid) |
| **6B** | Auto-discovery | High-conviction alt-data auto-adds unwatched names to the watchlist behind caps + liquidity-aware sizing |
| **7A** | Micro-capital validation | `BrokerAdapter` + Alpaca (paper→live), Assisted-only real orders at $250–500, reconciliation, order state machine, in-flight recovery |
| **7B** | Execution realism + 2nd venue | Kraken live crypto, venue routing, friction model recalibrated from live fills, per-venue reconciliation |
| **7C** | Graduated capital ramp | Stepwise size increases gated on clean reconciliation, live limits re-tuned, operational runbook |
| **7D** | Live semi-auto | Bounded autonomous execution (Appendix B Assisted→Semi-auto gate), full-strength demotion triggers |
| **8** | Scale + Autonomy | Full equities adapter, supervised-auto mode, correlation risk, Strategy Lab, Postgres migration path |
| **9** | Harden + Extend | Performance, service extraction, advanced observability, disaster recovery |

Phase 6 (alt-data) rationale and design: [`docs/adr/010-roadmap-rescope-alt-data-phase6.md`](docs/adr/010-roadmap-rescope-alt-data-phase6.md). Phase 7 (live trading) breakdown with entry gates and exit checklists: [`docs/phase-6-plan.md`](docs/phase-6-plan.md) (filename retained; renumbered per ADR-010). Execution venue decision: [`docs/adr/009-live-execution-venue.md`](docs/adr/009-live-execution-venue.md).

---

## API Key Policy

**Read-only. Withdrawal-disabled. Never committed.**

Real API keys go in `.env` (gitignored). The `.env.example` template contains no real values. Phases 0–5 use only public WebSocket/REST endpoints. Phase 6A's live feeds use free-tier *data* sources only — SEC EDGAR (insider), Senate LDA + USASpending (gov-exposure), and SEC 10-Ks (supply-chain) need **no key**; equity price data uses a free Alpaca/Polygon data key (`EQUITY_FEED_API_KEY`). Congress (Quiver) would need a free token but is dormant. **No exchange/execution key** is needed until live trading in Phase 7.

See [`docs/adr/003-api-key-security.md`](docs/adr/003-api-key-security.md).

---

## License

[Elastic License 2.0](LICENSE) — free to use and contribute; you may not redistribute or offer it as a product or service.
