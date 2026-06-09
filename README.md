# AFTERHOURS

> AI-assisted trading terminal for single-operator, own-capital use.

A modular monolith that connects live market data, LLM-generated trade theses, a deterministic risk engine, and a real-time browser terminal — with graduated human oversight at every level of autonomy.

---

## Status

**Phase 1 complete.** Live market data and signals flow end-to-end:

```
Kraken WebSocket → InProcessBus → SQLiteEventStore → FastAPI /ws → React terminal
                                        ↑
              PriceAlertGenerator (ticks → signal.created)
              RSSNewsFeed         (CoinDesk / CoinTelegraph → signal.created)
```

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
┌─────────────────────────────────────────────────────────┐
│                    AFTERHOURS process                    │
│                                                         │
│  ┌─────────────┐    ┌────────────────┐                  │
│  │  Ingestion  │───▶│  InProcessBus  │◀─── subscribers  │
│  │  (Coinbase) │    │                │                  │
│  └─────────────┘    │  persist-first │                  │
│                     │  then fan-out  │                  │
│  ┌─────────────┐    └───────┬────────┘                  │
│  │  Risk Engine│            │                           │
│  │  (Phase 1+) │            ▼                           │
│  └─────────────┘    ┌────────────────┐                  │
│                     │ SqliteEventStore│                  │
│  ┌─────────────┐    │  (events table)│                  │
│  │  LLM Layer  │    └────────────────┘                  │
│  │  (Phase 1+) │                                        │
│  └─────────────┘    ┌────────────────┐                  │
│                     │    FastAPI     │                  │
│                     │  /ws /api      │                  │
│                     └───────┬────────┘                  │
└─────────────────────────────┼───────────────────────────┘
                              │ WebSocket
                     ┌────────▼────────┐
                     │  React terminal  │
                     │  (Vite + TS)     │
                     └─────────────────┘
```

All inter-subsystem communication flows through the event bus as `EventEnvelope` objects. Consumers subscribe by topic prefix (`"market.*"`, `"decision.*"`, `"*"`). The bus persists every event to SQLite before fan-out — the event store is the audit log.

See [`docs/architecture.md`](docs/architecture.md) for the full breakdown and [`docs/adr/`](docs/adr/) for key design decisions.

---

## Directory Structure

```
afterhours/
├── core/                   # Shared domain — schemas, event bus, DB
│   ├── schemas/            # Pydantic models: events, signals, decisions
│   ├── bus/                # InProcessBus, EventStore protocol, adapters
│   └── db/                 # aiosqlite connection, migration runner
│
├── ingestion/              # Market data feeds and signal generators
│   ├── kraken/             # Kraken WebSocket v2 (primary, no auth)
│   ├── coinbase/           # Coinbase Advanced Trade (deferred until Phase 4)
│   ├── alerts/             # PriceAlertGenerator — tick → signal.created
│   └── news/               # RSS feed poller (CoinDesk, CoinTelegraph)
│
├── gateway/                # FastAPI app — HTTP + WebSocket gateway
│
├── frontend/               # React terminal UI
│   └── src/
│       ├── components/     # UI components — MarketWatch, SignalFeed, PanelShell
│       ├── hooks/          # useEventStream, useMarketTicks, useSignals
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

**Free data first.** All external data is behind adapters. Phases 0–3 use Kraken WebSocket v2 (no API key needed). Coinbase is preserved and ready; auth wiring deferred to Phase 4.

See [`PLANNING.md`](PLANNING.md) for the full non-negotiables list.

---

## Phase Roadmap

| Phase | Focus | Key Deliverable |
|---|---|---|
| **0** ✅ | Infrastructure | Live ticks end-to-end: exchange → bus → DB → screen |
| **1** ✅ | Signals | Price alerts + RSS news ingestion, SignalFeed panel |
| **2** | Thesis | LLM thesis generation, invalidation conditions |
| **3** | Risk engine | Deterministic sizing, stop-loss gating, kill switch |
| **4** | Execution | Paper trading, order lifecycle, fill reconciliation |
| **5** | Autonomy | Semi-auto mode, ECE measurement, demotion triggers |

---

## API Key Policy

**Read-only. Withdrawal-disabled. Never committed.**

Real API keys go in `.env` (gitignored). The `.env.example` template contains no real values. Phase 0–3 use only public WebSocket endpoints — no API key is needed.

See [`docs/adr/003-api-key-security.md`](docs/adr/003-api-key-security.md).

---

## License

[Elastic License 2.0](LICENSE) — free to use and contribute; you may not redistribute or offer it as a product or service.
