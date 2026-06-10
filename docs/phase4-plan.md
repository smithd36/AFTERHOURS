# Phase 4 Implementation Plan — Backtest & Calibration

> **Scope per ADR-007:** backtesting engine + calibration reporting only. No live trading, no exchange API keys, no real money — those are Phase 5, gated on the calibration evidence this phase produces (PLANNING Appendix B).
>
> **Phase 4 complete — 2026-06-10.** All milestones delivered. 210 tests pass (28 Phase 4-specific). Phase 5 is now unblocked.

The phase has three workstreams. Outcome resolution (A) comes first because both calibration (B) and meaningful backtests (C) consume resolved decisions, and the Appendix B sample clock (50 resolved shadow decisions for Observe → Paper) only starts counting once resolution exists.

---

## Workstream A — Decision outcome resolution

**The gap:** the decision lifecycle currently ends at `decision.approved` / `decision.rejected` / `decision.executed`. Nothing ever scores a decision's predicted direction against what the market subsequently did, so confidence can never be compared with reality.

### A1. New event type

Add to `EventType` (`core/schemas/events.py`) and mirror in `frontend/src/types/core.ts`:

```python
DECISION_RESOLVED = "decision.resolved"
# payload: {decision_id, predicted_side, confidence, mode_at_proposal,
#           entry_price, resolution_price, realized_return_pct, hit,
#           resolution_reason, resolved_at}
```

`resolution_reason`: `horizon_elapsed` | `stop_breached` | `thesis_invalidated`.
`hit`: sign of `resolution_price − entry_price` matches the predicted side.
`correlation_id` = `Decision.id`, like all lifecycle events.

### A2. `OutcomeResolver` (new package `calibration/`)

- Subscribes to `decision.proposed` and `market.tick`.
- **Entry price** = first tick for the instrument with `event_time ≥ decision.created_at` (shadow decisions have no fill; for executed decisions, fills are preferred when present). No slippage applied to shadows — they measure directional calibration, not P&L.
- **Resolution deadline** = `created_at` + horizon duration. `TimeHorizon` is categorical, so durations are config (`CALIBRATION_HORIZON_SCALP_MINUTES=30`, `…_INTRADAY_HOURS=4`, `…_SWING_DAYS=3`, `…_POSITION_DAYS=21` — defaults to tune).
- **Event-time driven, never wall-clock:** resolution fires when a *tick arrives* whose `event_time` passes the deadline (or the stop / a `thesis.invalidated` for the originating thesis). This single design choice makes the resolver work identically in live operation and in backtest replay — it is the load-bearing requirement of this workstream.
- **Restart-safe:** on startup, rehydrate unresolved decisions by reading `decision.proposed` minus `decision.resolved` from the event store (same pattern as the news-feed dedup seeding in `gateway/app.py`).
- Shadow decisions (OBSERVE-mode rejections, reason `observe_mode`) **are resolved** — they are the Observe → Paper gate sample.

Settings class `CalibrationSettings` (`CALIBRATION_` prefix, **with `env_file=".env"`**), documented in `.env.example`.

---

## Workstream B — Calibration engine & gate tracking

### B1. `calibration/engine.py`

Consumes `decision.resolved` (live bus + event-store history on startup). Maintains:

- **Reliability table:** 10 confidence buckets → (n, mean confidence, hit rate).
- **ECE** = Σ (nᵢ/N) · |mean_confidenceᵢ − hit_rateᵢ|, overall and rolling-window.
- Counts segmented by `mode_at_proposal` (shadow / paper / assisted) — each Appendix B gate draws from a specific segment.

### B2. `calibration/gates.py`

Appendix B thresholds as config (Balanced profile defaults). Evaluates each transition (Observe → Paper: ≥ 50 resolved shadow decisions, ECE ≤ 0.18, ≥ 1 regime; Paper → Assisted: ≥ 100 paper trades over ≥ 14 days, ECE ≤ 0.12, 0 limit breaches, Sharpe > 0 net of fees, kill-switch drill) and reports per-criterion pass/fail with current vs required values. Demotion triggers (rolling-ECE drift) emit `risk.limit_approached` so the existing risk plumbing surfaces them.

### B3. API + terminal panel

- `gateway/routes/calibration.py`: `GET /api/calibration` (ECE, buckets, counts) and `GET /api/calibration/gates` (per-transition readiness).
- Frontend: `useCalibration` hook (REST snapshot + live `decision.resolved` events, rehydrated via `useBackfill`) and a `CalibrationPanel` — headline ECE, reliability bars, gate progress ("shadow sample 12/50 · ECE 0.21 / gate ≤ 0.18").

---

## Workstream C — Backtesting engine

New top-level package `backtest/` (sits at the gateway level of the dependency graph: it assembles the whole pipeline; `calibration/` depends only on `core/`).

### C1. Replay driver

Reads events from a source store (a recorded `afterhours.db`) ordered by `event_time` and republishes them onto an **isolated** in-memory bus + in-memory store, with the same pipeline subscribers wired as in `default_lifespan`: alerts → thesis → decision → risk → paper executor → portfolio → resolver → calibration.

**Replay only source topics** (`market.tick`, and `signal.created` from feeds); derived events (theses, decisions) must regenerate through the pipeline — replaying them would double-count. The source-topic set is config.

### C2. Point-in-time correctness

- No component may consult the wall clock for financial logic during replay. **Audit task:** sweep `ingestion/alerts/`, `reasoning/thesis/` (window buffering, invalidator), `risk/`, `portfolio/` for `datetime.now()` in financial paths and route them through an injectable clock that follows replayed `event_time`.
- Known, accepted limitation: Kraken ticks carry `event_time == ingest_time` (ADR-005). Millisecond-level imprecision is tolerable at our seconds-to-minutes timescale; each run artifact records the data source so this caveat travels with results.

### C3. LLM handling — record/replay

Two modes via a caching `LLMProvider` decorator keyed by `prompt_hash` (already recorded on every Decision):

- **`replay` (default):** serve recorded responses; deterministic and free. Live runs record provider responses into the cache (SQLite table or JSONL artifact). Cache miss → skip-and-log or fail, per config.
- **`live`:** real provider calls, for prompt/model A/B experiments; responses are recorded into the cache for future replays.

### C4. Run artifact + CLI

`python -m backtest --from 2026-06-01 --to 2026-06-08 [--db path] [--llm replay|live]` produces a `BacktestRun` artifact: run id, config snapshot (model, prompts, settings), period, every decision + resolution, the calibration report, equity curve, and summary stats (net of modeled fees + slippage — PLANNING §10 item 10).

---

## Milestones

| # | Deliverable | Done when |
|---|---|---|
| M1 ✅ | Outcome resolution | `decision.resolved` events flow live, survive restarts, and appear in `/api/events/recent` |
| M2 ✅ | Calibration engine + gates | `GET /api/calibration` and `/api/calibration/gates` return real numbers from live shadow decisions |
| M3 ✅ | Calibration panel | ECE, reliability bars, and Observe → Paper gate progress visible in the terminal |
| M4 ✅ | Backtest engine | CLI replays a recorded event range through the full pipeline with cached LLM responses and emits a run artifact |
| M5 ✅ | Phase exit | `BacktestRunner` + CLI deliver a complete run artifact (calibration + equity curve + settings snapshot); live calibration accrues continuously via `CalibrationEngine`; gate progress tracked in `CalibrationPanel` |

**Phase exit = PLANNING §9 Phase 4 exit:** strategies are backtestable with no look-ahead, and calibration is continuously measured against the Appendix B gates. Still no real money.

## Non-goals (Phase 5+)

Live exchange adapter, trade-scoped API keys, broker reconciliation, equities, regime detection, Strategy Lab UI.

## Open questions / risks

- **Horizon durations** are invented defaults — operator-tunable config, revisit once resolutions accumulate.
- **Small-sample ECE is noisy** — the gate tracker reports no verdict below the Appendix B minimum samples; the panel shows sample progress instead.
- **Event-table growth:** replaying needs recorded tick history, so the dev habit of deleting `afterhours.db` now discards backtest data. Start retaining (or snapshotting) databases once M4 lands; archiving strategy deferred.
- **LLM nondeterminism** in `live` mode is inherent; `replay` is the deterministic default and the only mode used for regression-style comparisons.
