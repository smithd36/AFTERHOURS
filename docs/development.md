# Development Guide

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend build toolchain |
| npm | 9+ | Frontend package manager |
| Git | any | Version control |

---

## Initial Setup

### 1. Python environment

```bash
# Create a project-local venv
python -m venv .venv

# Activate
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# Install all deps (including dev extras: pytest, mypy, ruff)
pip install -e ".[dev]"
```

### 2. Environment variables

```bash
cp .env.example .env
```

The defaults in `.env.example` work for local development. The primary crypto feed (Kraken WebSocket v2) requires no API key, so Phases 0–5 run with no secrets. The optional equity stub feed activates only when `EQUITY_FEED_API_KEY` is set (Alpaca/Polygon free tier); without it the equity feed runs in no-op mode.

If you are configuring private API access (future phases), add keys to `.env` only — never commit them. Keys must be **read-only** and **withdrawal-disabled**. See [`docs/adr/003-api-key-security.md`](adr/003-api-key-security.md).

### 3. Frontend

```bash
cd frontend
npm install
```

---

## Running Locally

Two processes are needed: the Python backend and the Vite dev server.

**Terminal 1 — backend:**
```bash
python -m gateway
# Starts uvicorn on http://localhost:8000 with --reload
```

**Terminal 2 — frontend:**
```bash
cd frontend
npm run dev
# Starts Vite on http://localhost:5173
# Proxies /api and /ws to localhost:8000 automatically
```

Open `http://localhost:5173`.

### Backend endpoints

| Endpoint | Description |
|---|---|
| `GET /api/health` | Liveness check — returns `{"status":"ok","timestamp":"..."}` |
| `GET /api/status` | Gateway status — includes `connected_clients` count |
| `WS /ws` | Event stream — sends `EventEnvelope` JSON for all bus events |
| `GET /api/events/recent?types=…&limit=…` | Recent events from the audit log (UI rehydration) |
| `GET /api/mode` / `POST /api/mode` | Read / change autonomy mode (validated transitions) |
| `GET /api/decisions` | All tracked decisions |
| `GET /api/decisions/pending` | Decisions awaiting operator action (Assisted mode) |
| `POST /api/decisions/{id}/execute` | Operator executes a pending decision |
| `POST /api/decisions/{id}/reject` | Operator rejects a pending decision |
| `GET /api/portfolio` | Paper portfolio snapshot — cash, positions, P&L |
| `POST /api/portfolio/positions/{instrument}/close` | Close an open paper position |
| `POST /api/halt` | Kill switch — emits `risk.halt`, forces OBSERVE mode |
| `GET /api/calibration` | ECE + reliability buckets, overall and per autonomy mode |
| `GET /api/calibration/gates` | Appendix B graduation-gate readiness (criteria + deferred list) |
| `GET /api/watchlist` | List active watchlist entries (`instrument`, `market`, `added_at`) |
| `POST /api/watchlist` | Add instrument — body `{"instrument": "AAPL", "market": "equity"}` |
| `DELETE /api/watchlist/{instrument}` | Remove instrument from watchlist |

---

## Running Tests

```bash
# All tests
pytest

# With coverage report
pytest --cov=core --cov=gateway --cov=ingestion --cov-report=term-missing

# A specific module
pytest tests/core/bus/
pytest tests/ingestion/coinbase/
pytest tests/gateway/
```

Tests run without network access — all external dependencies (Kraken/Coinbase WS, equity REST, RSS, DB) are replaced by fakes or in-memory adapters in the test fixtures.

Key fixtures:
- `InMemoryEventStore` — event store backed by a list; exposes `.events` for assertions
- `test_lifespan` in `tests/gateway/test_app.py` — wires real bus, no feed, no DB
- `FakeWebSocket` in `tests/gateway/test_broadcaster.py` — satisfies `WebSocketLike` protocol

---

## Type Checking

```bash
mypy .
```

Configuration lives in `pyproject.toml` under `[tool.mypy]`. Target is Python 3.11, strict mode is not yet enforced globally but is enforced on `core/`.

---

## Linting

```bash
ruff check .
ruff format .
```

Configuration lives in `pyproject.toml` under `[tool.ruff]`.

---

## Database

SQLite database file is `afterhours.db` (gitignored). It is created automatically on first backend startup and migrated via `core/db/migrate.py`.

Migrations live in `core/db/migrations/` as numbered `.sql` files (`001_create_events.sql`, etc.). The migration runner globs files in order, runs each as a script, and records applied migrations in `schema_migrations`.

WAL mode is enabled (`PRAGMA journal_mode=WAL`) so reads and writes do not block each other.

To reset the database during development:
```bash
rm afterhours.db afterhours.db-wal afterhours.db-shm 2>/dev/null; true
# Restart the backend — it will recreate and migrate
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | structlog level: DEBUG, INFO, WARNING, ERROR |
| `LOG_FORMAT` | `dev` | `dev` (human-readable) or `json` (structured) |
| `DB_PATH` | `afterhours.db` | SQLite database file path |
| `GATEWAY_HOST` | `0.0.0.0` | Host to bind the FastAPI server |
| `GATEWAY_PORT` | `8000` | Port to bind the FastAPI server |
| `WS_CLIENT_QUEUE_SIZE` | `512` | Per-client outbound WebSocket buffer; a slow client drops its own oldest messages rather than stalling the bus |
| `KRAKEN_PRODUCTS` | `["BTC-USD","ETH-USD"]` | Instruments to subscribe to (primary feed) |
| `COINBASE_WS_URL` | `wss://advanced-trade-ws.coinbase.com/ws` | Coinbase public WS endpoint (secondary feed; Phase 6) |
| `COINBASE_PRODUCTS` | `["BTC-USD","ETH-USD"]` | Product IDs to subscribe to |
| `NEWS_FEED_URLS` | CoinDesk + CoinTelegraph | RSS feeds to poll |
| `NEWS_POLL_INTERVAL_SECONDS` | `300` | RSS poll interval |
| `ALERT_PRICE_MOVE_PCT_THRESHOLD` | `0.5` | % move that fires a `pct_move` price alert |
| `ALERT_PRICE_MOVE_WINDOW_MINUTES` | `15` | Rolling window for the % move calculation |
| `CALIBRATION_HORIZON_SCALP_MINUTES` | `30` | When a `scalp` decision's prediction is scored |
| `CALIBRATION_HORIZON_INTRADAY_HOURS` | `4` | When an `intraday` decision is scored |
| `CALIBRATION_HORIZON_SWING_DAYS` | `3` | When a `swing` decision is scored |
| `CALIBRATION_HORIZON_POSITION_DAYS` | `21` | When a `position` decision is scored |
| `CALIBRATION_ECE_BUCKETS` | `10` | Confidence buckets for the ECE / reliability table |
| `CALIBRATION_GATE_*` | Appendix B | Graduation-gate thresholds (see `.env.example`) |
| `ALERT_COOLDOWN_MINUTES` | `10` | Min gap between repeat alerts of the same type |
| `LLM_PROVIDER` | `ollama` | `ollama` \| `groq` \| `mistral` \| `openrouter` \| `anthropic` \| `openai` |
| `THESIS_MIN_SIGNALS_TO_TRIGGER` | `3` | Signals per instrument needed to trigger a thesis |
| `THESIS_SIGNAL_WINDOW_MINUTES` | `15` | Window the trigger count must fall within |
| `RISK_*` | see `risk/settings.py` | Position/loss limits, stop-loss distance |
| `PORTFOLIO_*` | see `portfolio/settings.py` | Initial cash, simulated slippage and fees |
| `PORTFOLIO_PENDING_TTL_SECONDS` | `3600` | How long an ASSISTED-mode parked decision stays executable before auto-expiring |
| `WATCHLIST_DEFAULT_INSTRUMENTS` | `BTC-USD,ETH-USD` | Comma-separated instruments seeded on first run |
| `WATCHLIST_DEFAULT_MARKET` | `crypto` | Market for seeded instruments (`crypto` or `equity`) |
| `EQUITY_FEED_PROVIDER` | `alpaca` | REST polling provider (`alpaca` or `polygon`) |
| `EQUITY_FEED_API_KEY` | *(unset)* | API key for equity feed; unset = no-op mode |
| `EQUITY_FEED_API_SECRET` | *(unset)* | API secret (Alpaca only) |
| `EQUITY_POLL_INTERVAL_SECONDS` | `60` | How often to poll each equity instrument |
| `TICK_RETENTION_DAYS` | `30` | `market.tick` events older than this are pruned |
| `TICK_PRUNE_INTERVAL_HOURS` | `24` | How often `TickPruner` runs |

Variables are loaded from `.env` by pydantic-settings. All settings classes use `env_prefix` matching their module (e.g., `COINBASE_*` for `CoinbaseFeedSettings`). `.env.example` documents every variable.

---

## Frontend Development

The frontend is a standard Vite + React + TypeScript project.

```bash
cd frontend

npm run dev        # dev server with HMR
npm run build      # production build (tsc + vite build)
npm run typecheck  # tsc --noEmit (no emit, type-check only)
npm run lint       # eslint
```

**Tailwind v4:** Uses `@tailwindcss/vite` plugin — no PostCSS config needed. All theme tokens are defined in `src/index.css` using `@theme inline` and CSS custom properties.

**Path alias:** `@/` maps to `src/`. Configured in both `vite.config.ts` and `tsconfig.app.json`.

**shadcn/ui:** New-york style, zinc base, CSS variables enabled. Components are generated into `src/components/ui/`. Run `npx shadcn@latest add <component>` from the `frontend/` directory to add new components.

**Dev proxy:** Vite proxies `/api` and `/ws` to `localhost:8000`. The frontend code uses relative URLs — no hardcoded backend addresses.

---

## Running a Backtest

The backtest CLI replays a recorded event range through the full pipeline and writes a JSON run artifact:

```bash
# Replay all recorded history (LLM responses served from cache — free)
python -m backtest

# Replay a specific window
python -m backtest --from 2026-06-01 --to 2026-06-08

# Record fresh LLM responses (requires LLM_PROVIDER configured)
python -m backtest --llm live

# Shadow-decision-only mode
python -m backtest --mode observe

# Custom database and output directory
python -m backtest --db path/to/afterhours.db --out my_runs/
```

Run artifacts are written to `backtest_runs/` as `run_<timestamp>_<id_prefix>.json`. Each artifact contains the run window, event counts (replayed + generated), calibration report (ECE + reliability buckets), equity curve, portfolio snapshot, and the full settings snapshot used.

**Note:** the database must contain recorded `market.tick` and `signal.created` events for the requested window. Run the backend live for a while before backtesting. Deleting `afterhours.db` discards backtest source data.

---

## Project Structure (Python packages)

```
afterhours/
├── core/           # pip-installable as "afterhours-core"
├── ingestion/      # depends on core
├── reasoning/      # depends on core
├── risk/           # depends on core
├── portfolio/      # depends on core
├── calibration/    # depends on core
├── backtest/       # depends on calibration, portfolio, reasoning, risk
├── watchlist/      # depends on core
├── gateway/        # depends on all of the above
└── tests/          # tests for all packages
```

The packages share a single `pyproject.toml` and are installed together as an editable install (`pip install -e .`). Import paths are `from core.schemas import EventEnvelope`, `from backtest import BacktestRunner`, etc.
