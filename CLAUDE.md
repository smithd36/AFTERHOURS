# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AFTERHOURS — an AI-assisted trading terminal for single-operator, own-capital use. Modular monolith: Python backend (FastAPI + asyncio) and a React terminal frontend, communicating over a WebSocket event stream. Phase 3 complete (risk engine + paper trading); see `PLANNING.md` for the phase roadmap and non-negotiables, `docs/adr/` for design decisions.

## Commands

```bash
# Setup (Python 3.11+, Node 18+)
pip install -e ".[dev]"          # backend, from repo root (use a .venv)
cd frontend && npm install       # frontend

# Run (two terminals)
python -m gateway                # backend: uvicorn on :8000 with reload
cd frontend && npm run dev       # frontend: Vite on :5173, proxies /api and /ws to :8000

# Tests (no network needed — externals replaced by fakes in fixtures)
pytest                           # all tests (asyncio_mode=auto, coverage on core/ by default)
pytest tests/core/bus/           # one module
pytest tests/gateway/test_app.py # one file

# Lint / format / types (Python)
ruff check .
ruff format .
mypy .                           # strict mode globally (pyproject [tool.mypy])

# Frontend
cd frontend
npm run typecheck                # tsc --noEmit
npm run lint                     # eslint
npm run build                    # tsc + vite build
```

To reset the dev database, delete `afterhours.db*` and restart the backend — it recreates and migrates automatically (migrations are numbered `.sql` files in `core/db/migrations/`, run by `core/db/migrate.py`).

## Architecture

Everything runs in one process and communicates through `InProcessBus` (`core/bus/`) as `EventEnvelope` objects. **The bus persists every event to SQLite (events table) before fan-out** — the event store is the audit log. Subscribers match by topic prefix: `"market.tick"` (exact), `"decision.*"` (domain), `"*"` (everything). The topic registry is the `EventType` enum in `core/schemas/events.py`, mirrored in `frontend/src/types/core.ts` — keep both in sync when adding event types.

Pipeline (each stage subscribes to the bus and emits new events):

```
KrakenFeed (ingestion/kraken) ──► market.tick
PriceAlertGenerator (ingestion/alerts), RSSNewsFeed (ingestion/news) ──► signal.created
ThesisGenerator (reasoning/thesis, LLM call) ──► thesis.created / thesis.invalidated
DecisionGenerator (reasoning/decision, LLM call) ──► decision.proposed
RiskEngine (risk/) — deterministic sizing, limits, stop-loss ──► decision.approved/rejected
PaperExecutor + Portfolio (portfolio/) ──► order.*, portfolio.*
Broadcaster (gateway/broadcaster.py) ──► all events to browser via WS /ws
```

Everything is wired in `default_lifespan` in `gateway/app.py`. Tests pass a custom lifespan to `create_app()` to skip real feeds/DB (see `tests/gateway/test_app.py`). Shared state for REST routes (`gateway/routes/`: mode, decisions, portfolio, halt) lives on `app.state`.

Package dependency direction: `core/` has no dependencies on other subsystems; `ingestion/`, `reasoning/`, `risk/`, `portfolio/` depend on core; `gateway/` depends on all. Single `pyproject.toml`, single editable install.

### Domain invariants

- **Two-clock rule:** `EventEnvelope.event_time` (venue/source clock) is for all financial logic and backtesting; `ingest_time` (our clock) is for ops/latency only. Using `ingest_time` in financial decisions is a look-ahead-bias bug.
- **Decision object** (`core/schemas/decision.py`) is the central artifact — immutable once created; status transitions are new events, not mutations; `Decision.id` is the `correlation_id` for all lifecycle events. The LLM only provides `reasoning`, `evidence[]`, `confidence`, and direction. `size_usd` and the risk verdict are computed deterministically by the risk engine — never by the LLM.
- **Autonomy is graduated:** Observe → Paper → Assisted → Semi-auto → Supervised (`AutonomyMode`), with a kill switch (`/api/halt`, `risk.halt` event). Current phases support Observe/Paper/Assisted.
- **API keys:** read-only, withdrawal-disabled, `.env` only. Phases 0–4 use only public endpoints (Kraken WS v2 is the primary feed and needs no auth; Coinbase is the secondary feed, auth deferred to Phase 5 live trading).

### LLM layer

Providers are pluggable behind `LLMProvider` (`reasoning/llm/base.py`), selected by `LLM_PROVIDER` env var via `create_provider()`: ollama (default), groq, mistral, openrouter (free tiers), anthropic, openai. Decision prompts are hashed (`prompt_hash`) into the Decision for audit replay.

### Configuration

All settings are pydantic-settings classes loaded from `.env`, one per module with a matching `env_prefix` (e.g. `KRAKEN_*` → `ingestion/kraken/settings.py`, `LLM_*` → `reasoning/llm/settings.py`). `.env.example` documents every variable.

### Frontend

Vite + React + TypeScript + Tailwind v4 (`@tailwindcss/vite` plugin, no PostCSS config) + shadcn/ui (new-york, zinc; add components with `npx shadcn@latest add <name>` from `frontend/`). `@/` aliases `src/`. `useEventStream` owns the WS connection with backoff reconnect; per-domain hooks (`useMarketTicks`, `useSignals`, `useTheses`, `useDecisions`, `usePortfolio`) reduce events into panel state; `useBackfill` rehydrates panels on mount by replaying `GET /api/events/recent` history through the same reducers. Theme tokens (`--bullish`, `--bearish`, etc.) are CSS custom properties in `src/index.css`; the terminal is dark-only. Use relative URLs for backend calls — the dev proxy handles routing.

## Notes

- Ruff line length is 100; `ANN` (type annotation) lint rules apply everywhere except `tests/`.
