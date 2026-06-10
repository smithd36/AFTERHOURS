# Pre-Phase-6 GitHub Issues

> Formatted for copy-paste into GitHub Issues.
> Source review: `docs/pre-phase6-review.md` — codebase as of `cfdde0b`.
> Test status at review time: 247 passed, 5 skipped.

Each entry below is a standalone issue. Separator `---` marks issue boundaries.

---

---

## [CRITICAL] Kill switch does not kill pending decisions

**Labels:** `critical`, `risk-engine`, `phase-6-blocker`

### Summary
`POST /api/halt` publishes `risk.halt` and forces OBSERVE, but nothing subscribes to `risk.halt` (grep confirms zero consumers). Approved decisions parked in `PaperExecutor._pending` survive a halt and remain executable — a genuine kill-switch bypass.

### Details
- `PaperExecutor.execute()` (`portfolio/executor.py:73`) does not check the current mode. After a halt drops the system to OBSERVE, `POST /api/decisions/{id}/execute` still fills the parked decision.
- Planning §2.4: the kill switch "flattens or freezes everything." Today it does neither: open positions stay open (acceptable if documented as "freeze"), but the pending queue staying executable is unacceptable.

### Suggested Change
- `execute()` must refuse unless mode is ASSISTED (or higher).
- Halt and any mode change away from ASSISTED should clear or expire `_pending`, emitting audited `decision.expired` events.
- The executor and risk engine should subscribe to `risk.halt` directly rather than relying solely on the mode-change side effect.

**Related:** see also issue "Autonomy mode lives in four places" (2.2) — fix together as one change set.

---

---

## [CRITICAL] "Daily" loss circuit breaker is actually a lifetime breaker

**Labels:** `critical`, `portfolio`, `phase-6-blocker`

### Summary
`Portfolio.daily_realized_pnl` (`portfolio/ledger.py:33`) is incremented forever and never reset. There is no day-rollover anywhere (grep confirms). The risk engine's `max_daily_loss_pct` check (`risk/engine.py:113-119`) therefore compares a cumulative figure against a daily limit.

### Details
- Direction of failure is safe (it over-blocks), but the semantics are wrong.
- 5% cumulative realized loss permanently halts all new entries until restart.
- A restart silently resets the counter to zero (see also "Portfolio not rehydrated on restart").

### Suggested Change
Implement an explicit UTC-day rollover keyed on event time (replay-safe), or rename the field and the setting to reflect what they actually measure (`lifetime_realized_pnl` / `max_lifetime_loss_pct`).

---

---

## [CRITICAL] Short-position equity math inflates value when shorts lose

**Labels:** `critical`, `portfolio`, `phase-6-blocker`

### Summary
`Portfolio.total_value = cash + Σ position.current_value` (`portfolio/ledger.py:53-56`) with `current_value = current_price × quantity` (`portfolio/models.py:23-25`). For a SHORT, when price rises (a loss), `current_value` rises, so reported equity goes *up* as the short loses money.

### Details
`total_value` feeds both position sizing and the daily-loss breaker, so a losing short silently increases the size of the next trade and masks the true drawdown.

### Suggested Change
A short's contribution to equity should be `margin + unrealized_pnl` (= `2·entry·qty − current·qty` under the current margin model), not raw market value. Add a regression test covering a losing short scenario.

---

---

## [CRITICAL] Approved decisions can open positions with no stop-loss

**Labels:** `critical`, `risk-engine`, `phase-6-blocker`

### Summary
`risk/engine.py:136-141`: if no tick for the instrument has been seen yet, `stop_price` is `None` and the decision is still approved. The fill then opens a position with `stop_price=None`, and the stop monitor explicitly skips such positions (`risk/engine.py:209-210`). Result: an unprotected position the risk engine will never close.

### Details
Planning §6.3: "never fail *open* into more risk." A position without a stop is exactly that.

### Suggested Change
Reject (or defer) any proposal for which a stop cannot be computed. A position without a stop should be impossible by construction — enforce this at approval time, not at monitoring time.

---

---

## [CRITICAL] ASSISTED-mode approvals go stale with no expiry or re-validation

**Labels:** `critical`, `risk-engine`, `phase-6-blocker`

### Summary
A decision parked in `_pending` can be executed hours or days after approval with no checks re-run and no expiry enforced.

### Details
- No TTL — the `Decision` schema has an `expired` status that is never used.
- `execute()` re-checks nothing: not the position-count limit, not the daily-loss breaker, not whether the instrument is already held.
- The stop price used at fill is the one computed from the *approval-time* price, which may be on the wrong side of the market by execution time.
- `_pending` is in-memory only — approved-but-unexecuted decisions vanish on restart with no audit event.

### Suggested Change
- Give parked decisions a TTL; emit `decision.expired` when they expire (including on restart).
- On `execute()`, re-run all pre-trade checks and recompute the stop from the current price.
- Persisting `_pending` across restarts is optional if expiry-on-restart is emitted as an audited event.

---

---

## [CRITICAL] Operator rejection is unaudited and reaches into private state

**Labels:** `critical`, `audit`, `phase-6-blocker`

### Summary
The `gateway/routes/decisions.py` reject endpoint pops `executor._pending` directly (private attribute) and publishes no event. A rejection leaves no trace in the audit log.

### Details
- Planning §7.2 calls operator rejections-with-reasons "training gold."
- Planning §2.10 requires every operator action in the audit trail.
- After a rejection: the decision stays in `decision_store` as "approved," the resolver keeps tracking it, and there is no reason capture.

### Suggested Change
Add a public `PaperExecutor.reject(decision_id, reason)` method that emits a `decision.rejected` (or `decision.operator_rejected`) event with `human: {actor, action, note, ts}` per the Decision schema in planning §3.4. Accept a `reason` field in the request body.

---

---

## [CRITICAL] Price quantization breaks on sub-cent instruments

**Labels:** `critical`, `risk-engine`, `phase-6-blocker`

### Summary
`stop_price.quantize(Decimal("0.01"))` (`risk/engine.py:141`) and `fill_price.quantize(Decimal("0.01"))` (`portfolio/executor.py:174`) use a hard-coded cent precision. For SHIB/PEPE-class prices (e.g. $0.00002), the stop quantizes to `0.00` and fills round to garbage.

### Details
Phase 5 lets the operator watch any Kraken pair. A stop of zero on a long can never trigger. Sizing (`size_usd / fill_price`) divides by a rounded price, producing wildly incorrect quantities.

### Suggested Change
Drop the hard-coded cent quantization (paper fills don't need it), or quantize per-instrument tick size carried on the instrument metadata.

---

---

## [IMPORTANT] No affordability check — cash can go negative

**Labels:** `important`, `portfolio`

### Summary
Sizing caps at `max_position_pct × total_value` (`risk/sizing.py`), but nothing checks available cash. `Portfolio.open_position` does an unconditional `cash -= cost_usd` (`portfolio/ledger.py:105`) and the executor doesn't check either.

### Details
With current defaults (5 × 5%) this won't trip in practice, but `total_value` includes position value, so after drawdowns `cash < size` is reachable. This is silent, meaningless leverage in the paper model and a latent bug for the live adapter. Planning §2.4 lists "can we afford it" as a required pre-trade check.

### Suggested Change
Risk engine should cap size at available cash (minus fee headroom) and reject when that's below a minimum trade size.

---

---

## [IMPORTANT] Autonomy mode lives in four places

**Labels:** `important`, `architecture`

### Summary
`app.state.autonomy_mode`, `RiskEngine._mode`, `PaperExecutor._mode`, and `OutcomeResolver._mode` are each synced by independently handling `system.mode_changed`. A missed or disordered event in Phase 6 means trading in the wrong mode.

### Details
The mode route also mutates `app.state` *after* publishing, so consumers and `app.state` can briefly disagree. Phase 6 adds a live executor where this race has real money consequences.

### Suggested Change
Introduce a single `ModeController` (publishes the event, owns the value, components query it) so there is exactly one source of truth. Keep restart-resets-to-OBSERVE as the fail-safe, but document it as intentional.

**Related:** fix together with "Kill switch does not kill pending decisions" (1.1).

---

---

## [IMPORTANT] Gateway is unauthenticated and binds 0.0.0.0

**Labels:** `important`, `security`

### Summary
`GatewaySettings.host` defaults to `0.0.0.0` (`gateway/settings.py`) and every endpoint — `/api/halt`, `/api/mode`, `/api/decisions/{id}/execute` — is open with no authentication.

### Details
Tolerable for localhost paper trading. Disqualifying for a console that will hold live, trade-scoped keys. Planning §6.4: "auth it like a bank."

### Suggested Change
- **Now (pre-Phase 6):** Default host to `127.0.0.1`.
- **Phase 6 (blocking before live keys):** Authentication on all state-changing routes and the WS endpoint.

---

---

## [IMPORTANT] Portfolio and decision state are not rehydrated on restart

**Labels:** `important`, `durability`

### Summary
Every restart resets the paper portfolio to `initial_cash`, drops open paper positions (the `order.filled` history is in the event store but never replayed), and rebuilds `decision_store` empty.

### Details
The calibration resolver *does* rehydrate — this asymmetry is the core problem. The Paper → Assisted gate requires "100 paper trades, ≥14 days" (Appendix B), and that evidence window can't survive restarts if the portfolio resets. P&L-based gates (Sharpe floor, 0 limit breaches) are measured against a portfolio that forgets its losses.

### Suggested Change
Rehydrate `Portfolio` from `order.filled` events at startup (mirroring the resolver's seed/replay pattern) and rebuild `decision_store` from recent decision events.

---

---

## [IMPORTANT] One slow WebSocket client stalls the whole pipeline

**Labels:** `important`, `gateway`, `performance`

### Summary
`InProcessBus.publish()` awaits full fan-out. `Broadcaster._fanout` (`gateway/broadcaster.py:89-95`) awaits `send_text` sequentially per client. A client with a congested connection back-pressures every publisher — including the Kraken dispatch loop and the risk engine's tick path.

### Details
Dead clients are only pruned when a send raises, which a stalled-but-open socket never does.

### Suggested Change
Per-client outbound queue (bounded, drop-oldest) with a writer task per client, or at minimum wrap sends in a short `asyncio.timeout`.

---

---

## [IMPORTANT] LLM output is not schema-validated or range-checked

**Labels:** `important`, `reasoning`, `data-integrity`

### Summary
`DecisionGenerator` (`reasoning/decision/generator.py:171-178`) takes model JSON nearly verbatim. Invalid or out-of-range values corrupt calibration buckets and can cause state divergence.

### Details
- `confidence: float(...)` is unchecked — a model emitting `7` or `-0.3` flows straight into calibration buckets and corrupts the evidence the autonomy gates depend on.
- `side` is an unvalidated string; anything besides `long|short` propagates until `Side(side_str)` raises inside the ledger's fill handler — *after* the fill event is already in the audit log (fill recorded, position never opened: state divergence).
- Empty `evidence` is accepted; planning §6.2: "no evidence → no trade."

### Suggested Change
Validate the assembled payload against the `Decision` pydantic schema before publishing. Clamp/reject out-of-range confidence. Reject invalid side. Drop proposals with no resolvable evidence. Planning §4.5 explicitly requires "schema-validated, range-checked."

---

---

## [IMPORTANT] Realized P&L excludes the entry fee

**Labels:** `important`, `portfolio`

### Summary
Open fee is deducted from cash (`cost_usd + fee`, `portfolio/executor.py` → `portfolio/ledger.py:172`) but `close_position` only subtracts the *close* fee from realized P&L (`portfolio/ledger.py:124-133`).

### Details
The Appendix B gate "Sharpe > 0 *net of modeled fees + slippage*" is therefore measured on flattered P&L numbers. The entry fee effectively disappears from the books once the position closes.

### Suggested Change
Include the entry fee in the cost basis — store it on `Position` at open time and factor it into realized P&L at close.

---

---

## [HYGIENE] Gateway reaches into feed private state directly

**Labels:** `hygiene`, `architecture`

`gateway/app.py:176` calls `kraken_feed._active_instruments.clear()` directly. Replace with a constructor flag (`products=[]` via settings, or `start_empty=True`).

---

---

## [HYGIENE] KrakenFeed._ws not cleared on connection error

**Labels:** `hygiene`, `ingestion`

`ingestion/kraken/feed.py:109-125`: `_ws` is not set to `None` on connection error. A `subscribe()` call during the reconnect window sends on a dead socket and raises into the bus handler.

**Fix:** set `self._ws = None` in a `finally` block around the connection block.

---

---

## [HYGIENE] Kraken subscribe failures give no feedback to the operator

**Labels:** `hygiene`, `ingestion`, `ux`

`ingestion/kraken/feed.py:157-166`: subscribe failures (e.g. operator adds a symbol Kraken doesn't list) are only logged. The watchlist keeps the instrument and the UI indicator stays stale with no feedback loop.

**Fix:** correlate the failure to the instrument and emit a `system.feed_error`-style event that `WatchlistPanel` can surface.

---

---

## [HYGIENE] TickPruner never prunes on a process restarted daily

**Labels:** `hygiene`, `ingestion`

`ingestion/pruner.py:66-69`: `TickPruner` sleeps a full interval (24 h default) before the first prune. A process restarted daily never prunes.

**Fix:** prune once at startup, then enter the sleep loop.

---

---

## [HYGIENE] ThesisInvalidator expiry is wall-clock-keyed and lost on restart

**Labels:** `hygiene`, `reasoning`

`reasoning/thesis/invalidator.py`: expiry is keyed on `ingest_time` (wall clock) and `_active` is lost on restart, so pre-restart theses never expire. The resolver then waits out their full horizon against stale data.

**Fix:** rehydrate active theses from the store at startup; key expiry on `event_time` (this would also let backtests include invalidation, which is currently excluded).

---

---

## [HYGIENE] Unbounded in-memory growth in decision store and generator

**Labels:** `hygiene`, `performance`

Three structures grow without bound:
- `decision_store` dict — `gateway/app.py:108`
- `DecisionGenerator._processed_thesis_ids`
- `OutcomeResolver._last_price`

Harmless for days; not for an always-on process.

**Fix:** cap each with an LRU or `collections.deque(maxlen=N)`.

---

---

## [HYGIENE] SqliteEventStore commits per-event (one fsync per tick)

**Labels:** `hygiene`, `performance`

`core/bus/store.py:120-138`: `SqliteEventStore.append` commits per event. Fine today; will hurt as the watchlist grows and tick volume increases.

**Note:** not worth changing until it shows up in profiling — track here so it's not forgotten.

---

---

## [HYGIENE] Migration runner has a crash window between executescript and tracking INSERT

**Labels:** `hygiene`, `database`

`core/db/migrate.py`: `executescript` auto-commits before the tracking `INSERT`, so a crash between the two re-runs the migration on next boot.

**Note:** currently safe because every migration is `IF NOT EXISTS`-idempotent. Make that an explicit, documented invariant that must hold for all future migrations.

---

---

## [HYGIENE] DecisionGenerator imports private function from ThesisGenerator

**Labels:** `hygiene`, `architecture`

`reasoning/decision/generator.py:29` imports `_extract_json` (prefixed private) from `reasoning.thesis.generator`.

**Fix:** promote to a shared `reasoning/llm/json_utils.py` module.

---

---

## [HYGIENE] No idempotency key from decision → order → fill (paper acceptable, live is not)

**Labels:** `hygiene`, `architecture`, `phase-6-prep`

`portfolio/executor.py`: duplicate-fill protection relies entirely on in-process delivery semantics with no client order ID. Acceptable for paper; the Phase 6 live adapter must introduce client order IDs keyed on `decision.id` (planning §2.5).

**Fix:** design the `Order` flow now so paper and live share the same structure — avoids a breaking refactor mid-Phase 6.

---
