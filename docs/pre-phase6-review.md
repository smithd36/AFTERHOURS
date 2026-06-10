# Pre-Phase-6 Codebase Review

> **Date:** 2026-06-10
> **Scope:** full review of the codebase as of `cfdde0b` (Phase 5 complete), looking for changes that should land **before Phase 6 — Live Trading (Assisted)** begins.
> **Test status at review time:** 247 passed, 5 skipped.

Phase 6 is the first phase where real money is at stake, so this review weighs everything against the planning doc's non-negotiables: deterministic risk engine as authoritative gatekeeper, kill switch always effective, full audit trail, calibration integrity (planning.md §12 #5).

Findings are grouped by severity. File references are to the current `main`.

---

## 1. Critical — fix before any Phase 6 work

### 1.1 The kill switch does not kill pending decisions
- `POST /api/halt` publishes `risk.halt` and forces OBSERVE — but **nothing subscribes to `risk.halt`** (grep confirms zero consumers).
- `PaperExecutor._pending` (parked ASSISTED decisions) survives a halt. Worse, `PaperExecutor.execute()` (`portfolio/executor.py:73`) **does not check the current mode** — after a halt drops the system to OBSERVE, `POST /api/decisions/{id}/execute` still fills the parked decision.
- Planning §2.4: the kill switch "flattens or freezes everything." Today it does neither: open positions stay open (acceptable if documented as "freeze"), but the pending queue staying executable is a genuine kill-switch bypass.

**Change:** (a) `execute()` must refuse unless mode is ASSISTED (or higher); (b) halt and any mode change away from ASSISTED should clear or expire `_pending`, emitting audited `decision.expired` events; (c) the executor and risk engine should subscribe to `risk.halt` directly rather than relying solely on the mode-change side effect.

### 1.2 "Daily" loss circuit breaker is actually a lifetime breaker
`Portfolio.daily_realized_pnl` (`portfolio/ledger.py:33`) is incremented forever and **never reset** — there is no day-rollover anywhere (grep confirms). The risk engine's `max_daily_loss_pct` check (`risk/engine.py:113-119`) therefore compares a cumulative figure against a daily limit. Direction of failure is safe (it over-blocks), but the semantics are wrong: 5% cumulative realized loss permanently halts all new entries until restart, and a restart silently resets it to zero (see 2.4).

**Change:** implement an explicit UTC-day rollover keyed on event time (replay-safe), or rename the field and the setting to reflect what they actually measure.

### 1.3 Short-position equity math inflates value when shorts lose
`Portfolio.total_value = cash + Σ position.current_value` (`portfolio/ledger.py:53-56`) with `current_value = current_price × quantity` (`portfolio/models.py:23-25`). For a SHORT, when price rises (a loss), `current_value` **rises**, so reported equity goes *up* as the short loses money. `total_value` feeds position sizing and the daily-loss breaker, so a losing short increases the size of the next trade.

**Change:** a short's contribution to equity should be `margin + unrealized_pnl` (= `2·entry·qty − current·qty` under the current margin model), not market value. Add a regression test with a losing short.

### 1.4 Approved decisions can open positions with no stop-loss
`risk/engine.py:136-141`: if no tick for the instrument has been seen yet, `stop_price` is `None` and the decision is **still approved**. The fill then opens a position with `stop_price=None`, and the stop monitor explicitly skips such positions (`risk/engine.py:209-210`). Result: an unprotected position the risk engine will never close. Planning §6.3: "never fail *open* into more risk."

**Change:** reject (or defer) any proposal for which a stop cannot be computed. A position without a stop should be impossible by construction.

### 1.5 ASSISTED-mode approvals go stale, with no expiry or re-validation
A decision parked in `_pending` can be executed hours or days later:
- No TTL — the Decision schema has an `expired` status that is never used.
- `execute()` re-checks nothing: not the position-count limit, not the daily-loss breaker, not whether the instrument is already held, and the stop price is the one computed from the *approval-time* price, which may be on the wrong side of the market by execution time.
- `_pending` is in-memory only — approved-but-unexecuted decisions vanish on restart with no audit event.

**Change:** give parked decisions a TTL (emit `decision.expired`); on `execute()`, re-run the pre-trade checks and recompute the stop from the current price. Persisting `_pending` is optional if expiry-on-restart is emitted as an audited event.

### 1.6 Operator rejection is unaudited and reaches into private state
`gateway/routes/decisions.py` reject endpoint pops `executor._pending` directly (private attribute) and **publishes no event**. Planning §7.2 calls operator rejections-with-reasons "training gold," and §2.10 requires every operator action in the audit trail. Today a rejection leaves no trace: the decision stays in `decision_store` as "approved," the resolver keeps tracking it, and there is no reason capture.

**Change:** add a public `PaperExecutor.reject(decision_id, reason)` that emits a `decision.rejected` (or new `decision.operator_rejected`) event with `human: {actor, action, note, ts}` per the Decision schema in planning §3.4. Accept a `reason` in the request body.

### 1.7 Price quantization breaks on sub-cent instruments
`stop_price.quantize(Decimal("0.01"))` (`risk/engine.py:141`) and `fill_price.quantize(Decimal("0.01"))` (`portfolio/executor.py:174`). Phase 5 lets the operator watch *any* Kraken pair; for SHIB/PEPE-class prices ($0.00002) the stop quantizes to `0.00` and fills quantize to garbage. A stop of zero on a long can never trigger; sizing (`size_usd / fill_price`) divides by a rounded price.

**Change:** drop the hard-coded cent quantization (paper fills don't need it), or quantize per-instrument tick size carried on the instrument metadata.

---

## 2. Important — fix before or at the start of Phase 6

### 2.1 No affordability check — cash can go negative
Sizing caps at `max_position_pct × total_value` (`risk/sizing.py`), but nothing checks **available cash**: `Portfolio.open_position` does an unconditional `cash -= cost_usd` (`portfolio/ledger.py:105`) and the executor doesn't check either. With current defaults (5 × 5%) this won't trip in practice, but `total_value` includes position value, so after drawdowns `cash < size` is reachable — silent, meaningless leverage in the paper model and a latent bug for the live adapter. Planning §2.4 lists "can we afford it" as a pre-trade check.

**Change:** risk engine should cap size at available cash (minus fee headroom) and reject when that's below a minimum trade size.

### 2.2 Autonomy mode lives in four places
`app.state.autonomy_mode`, `RiskEngine._mode`, `PaperExecutor._mode`, `OutcomeResolver._mode` — each synced by independently handling `system.mode_changed`. It works today, but Phase 6 adds a live executor where a missed/disordered event means **trading in the wrong mode**. Also note the mode route mutates `app.state` *after* publishing, so consumers and `app.state` can briefly disagree.

**Change:** introduce a single `ModeController` (publishes the event, owns the value, components query it) so there is exactly one source of truth. Keep restart-resets-to-OBSERVE — it's the right fail-safe — but document it as intentional.

### 2.3 Gateway is unauthenticated and binds 0.0.0.0
`GatewaySettings.host` defaults to `0.0.0.0` (`gateway/settings.py`) and every endpoint — `/api/halt`, `/api/mode`, `/api/decisions/{id}/execute` — is open. Tolerable for localhost paper trading; disqualifying for a console that will hold live, trade-scoped keys (planning §6.4: "auth it like a bank").

**Change now:** default host to `127.0.0.1`. **Change in Phase 6 (blocking):** authentication on all state-changing routes + the WS endpoint, before any live key is configured.

### 2.4 Portfolio and decision state are not rehydrated on restart
Every restart resets the paper portfolio to `initial_cash`, drops open paper positions (the `order.filled` history is in the event store but never replayed), and rebuilds `decision_store` empty so `GET /api/decisions` forgets history. The calibration resolver *does* rehydrate — the asymmetry is the problem: the Paper → Assisted gate needs "100 paper trades, ≥14 days" (Appendix B), and that evidence window can't survive restarts if the portfolio resets daily. P&L-based gates (Sharpe floor, 0 limit breaches) are measured against a portfolio that forgets its losses.

**Change:** rehydrate `Portfolio` from `order.filled` events at startup (mirroring the resolver's seed/replay pattern), and rebuild `decision_store` from recent decision events.

### 2.5 One slow WebSocket client stalls the whole pipeline
`InProcessBus.publish()` awaits full fan-out; `Broadcaster._fanout` (`gateway/broadcaster.py:89-95`) awaits `send_text` **sequentially per client**. A client with a congested connection back-pressures every publisher — including the Kraken dispatch loop and the risk engine's tick path. Dead clients are only pruned when a send raises, which a stalled-but-open socket never does.

**Change:** per-client outbound queue (bounded, drop-oldest) with a writer task per client, or at minimum wrap sends in a short `asyncio.timeout`.

### 2.6 LLM output is not schema-validated or range-checked
`DecisionGenerator` (`reasoning/decision/generator.py:171-178`) takes the model's JSON nearly verbatim:
- `confidence: float(...)` unchecked — a model emitting `7` or `-0.3` flows straight into the calibration buckets and corrupts the very evidence the autonomy gates depend on.
- `side` is an unvalidated string; anything but `long|short` would propagate until `Side(side_str)` raises inside the ledger's fill handler — *after* the fill event is already in the audit log (fill recorded, position never opened: state divergence).
- Empty `evidence` is accepted; planning §6.2 says "no evidence → no trade."

**Change:** validate the assembled payload against the `Decision` pydantic schema before publishing; clamp/reject out-of-range confidence; reject invalid side; drop proposals with no resolvable evidence. Planning §4.5 explicitly requires "schema-validated, range-checked."

### 2.7 Realized P&L excludes the entry fee
Open fee is deducted from cash (`cost_usd + fee`, `portfolio/executor.py` → `ledger.py:172`) but `close_position` only subtracts the **close** fee from realized P&L (`portfolio/ledger.py:124-133`). The Appendix B gate "Sharpe > 0 *net of modeled fees + slippage*" is therefore measured on flattered numbers.

**Change:** include the entry fee in the cost basis (store it on `Position`).

---

## 3. Worth fixing — hygiene and robustness

| # | Issue | Location | Suggested change |
|---|---|---|---|
| 3.1 | Gateway reaches into `kraken_feed._active_instruments.clear()` | `gateway/app.py:176` | Constructor flag (`products=[]` via settings, or `start_empty=True`) |
| 3.2 | `KrakenFeed._ws` not cleared on connection error — `subscribe()` during the reconnect window sends on a dead socket and raises into the bus handler | `ingestion/kraken/feed.py:109-125` | Set `self._ws = None` in a `finally` around the connection block |
| 3.3 | Kraken subscribe failures (e.g. operator adds a symbol Kraken doesn't list) are only logged — watchlist keeps the instrument, UI indicator just stays stale, no feedback loop | `ingestion/kraken/feed.py:157-166` | Correlate failure to instrument, emit a `system.feed_error`-style event the WatchlistPanel can surface |
| 3.4 | `TickPruner` sleeps a full interval (24 h default) before the first prune — a process restarted daily never prunes | `ingestion/pruner.py:66-69` | Prune once at startup, then loop |
| 3.5 | `ThesisInvalidator` keys expiry on `ingest_time`/wall clock and `_active` is lost on restart, so pre-restart theses never expire (resolver then waits out their full horizon) | `reasoning/thesis/invalidator.py` | Rehydrate active theses from the store at startup; key expiry on `event_time` (would also let backtests include invalidation, currently excluded) |
| 3.6 | Unbounded in-memory growth: `decision_store` dict (`gateway/app.py:108`), `DecisionGenerator._processed_thesis_ids`, `OutcomeResolver._last_price` | various | Cap with LRU/maxlen; harmless for weeks, not for an always-on process |
| 3.7 | `SqliteEventStore.append` commits per event — one fsync per tick; fine today, will hurt as watchlist grows | `core/bus/store.py:120-138` | Consider batched commits behind the same interface when it shows up in profiling |
| 3.8 | Migration runner: `executescript` auto-commits before the tracking INSERT, so a crash in between re-runs the migration on next boot | `core/db/migrate.py` | Fine while every migration is `IF NOT EXISTS`-idempotent — make that an explicit documented rule |
| 3.9 | `DecisionGenerator` imports `_extract_json` (private) from `reasoning.thesis.generator` | `reasoning/decision/generator.py:29` | Promote to a shared `reasoning/llm/json_utils.py` |
| 3.10 | Duplicate-fill protection relies entirely on in-process delivery semantics — no idempotency key from decision → order → fill | `portfolio/executor.py` | Acceptable for paper; the Phase 6 live adapter must introduce client order IDs keyed on decision id (planning §2.5) — design the `Order` flow so paper and live share it |

---

## 4. Explicitly checked, no change needed

- **Two-clock discipline** is consistently respected in the risk engine, resolver, decision generator, and backtest runner (`event_time` for financial logic throughout). The one deliberate exception (ThesisInvalidator) is documented in `backtest/runner.py` — see 3.5.
- **Persist-before-fanout** bus contract (`core/bus/in_process.py`) is sound, and handler isolation is correct.
- **Event store** SQL is parameterized; `range()`'s lexicographic timestamp handling correctly normalizes to the `Z` suffix form.
- **Watchlist gating** is applied consistently across alerts, theses, decisions, and news.
- **Frontend** WS reconnect (backoff, ref-stable handler) and backfill-through-same-reducers pattern look correct; no changes needed there for Phase 6.

---

## 5. Suggested order of work

1. **Kill-switch integrity** (1.1) + **mode unification** (2.2) — one change set: ModeController, executor mode check, pending-queue expiry on halt.
2. **Ledger correctness** (1.2, 1.3, 2.1, 2.7) — one change set with regression tests; these all touch `portfolio/`.
3. **Risk-engine hardening** (1.4, 1.5, 1.7) — no-stop rejection, re-validation + TTL on execute, tick-size-aware quantization.
4. **Audit gaps** (1.6) — operator reject event + reason.
5. **LLM output validation** (2.6) — protects calibration data integrity before the sample that Phase 6 gates on starts accumulating.
6. **Restart durability** (2.4) — portfolio rehydration; required for the 14-day Paper → Assisted evidence window.
7. Items in §3 opportunistically, with 3.2/3.4/3.5 prioritized.

Items 1–6 are all pre-conditions for trusting the Appendix B gate measurements that Phase 6 entry depends on; starting the live-adapter work before the ledger and kill-switch fixes would mean re-measuring the paper sample afterwards anyway.
