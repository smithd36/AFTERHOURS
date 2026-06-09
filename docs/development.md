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

The defaults in `.env.example` work for local development. Coinbase public WebSocket data requires no API key.

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

Tests run without network access — all external dependencies (Coinbase WS, DB) are replaced by fakes or in-memory adapters in the test fixtures.

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
| `COINBASE_WS_URL` | `wss://advanced-trade-ws.coinbase.com/ws` | Coinbase public WS endpoint |
| `COINBASE_PRODUCTS` | `["BTC-USD","ETH-USD"]` | Product IDs to subscribe to |

Variables are loaded from `.env` by pydantic-settings. All settings classes use `env_prefix` matching their module (e.g., `COINBASE_*` for `CoinbaseFeedSettings`).

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

## Project Structure (Python packages)

```
afterhours/
├── core/           # pip-installable as "afterhours-core"
├── ingestion/      # depends on core
├── gateway/        # depends on core, ingestion
└── tests/          # tests for all packages
```

The packages share a single `pyproject.toml` and are installed together as an editable install (`pip install -e .`). Import paths are `from core.schemas import EventEnvelope`, `from ingestion.coinbase import CoinbaseFeed`, etc.
