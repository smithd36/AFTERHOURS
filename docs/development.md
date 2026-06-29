# Development Guide

> Part of the AFTERHOURS documentation set - see [`README.md`](README.md) for the index and current
> project stage.

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

If you are configuring private API access (future phases), add keys to `.env` only - never commit them. Keys must be **read-only** and **withdrawal-disabled**. See [`docs/adr/003-api-key-security.md`](adr/003-api-key-security.md).

### 3. Frontend

```bash
cd frontend
npm install
```

---

## Running Locally

Two processes are needed: the Python backend and the Vite dev server.

**Terminal 1 - backend:**
```bash
python -m gateway
# Starts uvicorn on http://localhost:8000 with --reload
```

**Terminal 2 - frontend:**
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
| `GET /api/health` | Liveness check - returns `{"status":"ok","timestamp":"..."}` |
| `GET /api/status` | Gateway status - includes `connected_clients` count |
| `WS /ws` | Event stream - sends `EventEnvelope` JSON for all bus events |
| `GET /api/events/recent?types=…&limit=…` | Recent events from the audit log (UI rehydration) |
| `GET /api/mode` / `POST /api/mode` | Read / change autonomy mode (validated transitions) |
| `GET /api/decisions` | All tracked decisions |
| `GET /api/decisions/pending` | Decisions awaiting operator action (Assisted mode) |
| `POST /api/decisions/{id}/execute` | Operator executes a pending decision |
| `POST /api/decisions/{id}/reject` | Operator rejects a pending decision |
| `GET /api/portfolio` | Paper portfolio snapshot - cash, positions, P&L |
| `POST /api/portfolio/positions/{instrument}/close` | Close an open paper position |
| `GET /api/portfolio/trades?date=…` | Fills for a NYSE day (today from the ledger; past dates from the event store) |
| `POST /api/halt` | Kill switch - emits `risk.halt`, forces OBSERVE mode |
| `GET /api/calibration` | ECE + reliability buckets, overall and per autonomy mode |
| `GET /api/calibration/gates` | Appendix B graduation-gate readiness (criteria + deferred list) |
| `GET /api/analytics` | Equity curve + Sharpe/Sortino/volatility/VaR/drawdown (economic gate read side) |
| `GET /api/watchlist` | List active watchlist entries (`instrument`, `market`, `added_at`) |
| `POST /api/watchlist` | Add instrument - body `{"instrument": "AAPL", "market": "equity"}` |
| `DELETE /api/watchlist/{instrument}` | Remove instrument from watchlist |
| `GET /api/discovery` | Ranked discovery candidates (on-demand confluence projection over unwatched names) |
| `GET /api/discovery/{instrument}/analysis` | Lazy per-candidate AI analyst pass (why-interesting + counter-signals) |
| `GET /api/chart?symbol=…&range=…` | Daily + intraday OHLC for a symbol (Kraken crypto / Alpaca equity) |

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

Tests run without network access - all external dependencies (Kraken/Coinbase WS, equity REST, RSS, DB) are replaced by fakes or in-memory adapters in the test fixtures.

Key fixtures:
- `InMemoryEventStore` - event store backed by a list; exposes `.events` for assertions
- `test_lifespan` in `tests/gateway/test_app.py` - wires real bus, no feed, no DB
- `FakeWebSocket` in `tests/gateway/test_broadcaster.py` - satisfies `WebSocketLike` protocol

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
# Restart the backend - it will recreate and migrate
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
| `LLM_MAX_RPM` | `-1` (auto) | Client-side requests/min ceiling (token bucket). `-1` = 25 for groq/mistral/openrouter, 0 elsewhere; `0` disables throttling |
| `LLM_MAX_CONCURRENCY` | `3` | Max simultaneous in-flight LLM calls (applied only when throttling is active) |
| `LLM_MAX_RETRIES` | `6` | 429 / transient-5xx retry budget, Retry-After-aware (OpenAI-compatible providers) |
| `LLM_JSON_MODE` | `true` | `response_format=json_object` on OpenAI-compatible providers; set `false` for models that reject it |
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

## LLM Providers - Rate Limiting & Resilience

Signal bursts (many instruments firing theses/decisions at once) can spike well past a provider's **per-minute** limit even when daily volume is tiny - this is the usual cause of free-tier `429`s. The LLM layer smooths and absorbs those bursts so a transient limit doesn't drop a thesis or decision.

**Where it sits.** `create_provider()` wraps the real provider in a `ThrottledProvider` (`reasoning/llm/throttle.py`), and `gateway/app.py` wraps *that* in `CachingProvider`:

```
CachingProvider → ThrottledProvider → {OpenAICompatible | Anthropic | OpenAI | Ollama}
```

Because the throttle sits **inside** the cache, a cache hit (replays, repeated prompts) returns immediately and never consumes a rate-limit permit.

**Three mechanisms:**

1. **Throttle (`ThrottledProvider`).** A requests-per-minute token bucket plus a concurrency semaphore. Bursts *queue* instead of slamming the provider. Tuned by `LLM_MAX_RPM` / `LLM_MAX_CONCURRENCY`. The bucket starts full, so a burst up to `LLM_MAX_RPM` is allowed immediately, then paced. Auto-enabled (25 rpm) for the free providers `groq`/`mistral`/`openrouter`; off for `ollama`/`anthropic`/`openai` unless you set `LLM_MAX_RPM` explicitly.
2. **Retry-After backoff (`OpenAICompatibleProvider`).** The OpenAI SDK's built-in retries are disabled (`max_retries=0`) so we own the loop and can read the rate-limit headers. A `429` is retried up to `LLM_MAX_RETRIES` times, honoring the `Retry-After` header (falling back to exponential backoff + jitter); transient 5xx/connection errors get plain backoff.
3. **JSON mode (`LLM_JSON_MODE`).** `response_format=json_object` makes the model emit valid JSON first try, cutting the generators' parse-retry round-trips (which otherwise silently double some calls).

**Diagnosing 429s.** Every rate-limited attempt logs an `llm.rate_limited` event with the actual bucket, so you can see *which* limit you hit:

```
llm.rate_limited  model=… attempt=1 retry_in_s=2.0
  limit_requests=30 remaining_requests=0      ← RPM hit → lower LLM_MAX_RPM
  limit_tokens=6000 remaining_tokens=5200     ← (TPM headroom fine here)
  retry_after=2
```

If `remaining_requests` hits 0 it's a requests-per-minute limit (lower `LLM_MAX_RPM`); if `remaining_tokens` hits 0 it's tokens-per-minute.

### Caveats

- **`LLM_MAX_RPM` defaults assume one provider account per process.** Provider rate limits are enforced **per-account (organization), not per-API-key** - multiple keys under one account share one bucket. If N instances share a single free account, set each box's `LLM_MAX_RPM` so the **sum** stays under the account's ceiling (e.g. 3 boxes on one Groq account ≈ `LLM_MAX_RPM=8` each, not the 25 default). Give each instance its own account to use the full default.
- **JSON mode is provider-dependent.** Groq and Mistral support `response_format=json_object`; some OpenRouter models reject it and return a `400`. Set `LLM_JSON_MODE=false` for those.
- **The throttle is a smoother, not a multiplier.** It paces you under a limit; it does not raise it. If you're genuinely over a provider's sustained capacity, you need a higher tier, more accounts, or a different provider.
- **Anthropic/OpenAI/Ollama are unthrottled by default.** They have generous limits (paid) or none (local). Set `LLM_MAX_RPM` > 0 to throttle them too.

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

**Tailwind v4:** Uses `@tailwindcss/vite` plugin - no PostCSS config needed. All theme tokens are defined in `src/index.css` using `@theme inline` and CSS custom properties.

**Path alias:** `@/` maps to `src/`. Configured in both `vite.config.ts` and `tsconfig.app.json`.

**shadcn/ui:** New-york style, zinc base, CSS variables enabled. Components are generated into `src/components/ui/`. Run `npx shadcn@latest add <component>` from the `frontend/` directory to add new components.

**Dev proxy:** Vite proxies `/api` and `/ws` to `localhost:8000`. The frontend code uses relative URLs - no hardcoded backend addresses.

---

## Running a Backtest

The backtest CLI replays a recorded event range through the full pipeline and writes a JSON run artifact:

```bash
# Replay all recorded history (LLM responses served from cache - free)
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
