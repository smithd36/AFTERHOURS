# ADR-011: A Dedicated Analytics Module for Risk/Return Measurement

**Status:** Accepted
**Date:** 2026-06-16
**Deciders:** Operator, @smithd36

---

## Context

The Phase 7A (live-trading) entry gate requires **"Sharpe > 0 net of modeled fees + slippage"**
(`docs/phase-6-plan.md`). The system cannot measure this today:
`GateTracker._paper_to_assisted` lists Sharpe under `deferred` with the note *"needs a return
series"*. We compute trade-sequence economics (`economic_metrics` in `calibration/gates.py` —
expectancy, win rate, profit factor, drawdown on the realized-trade curve) but nothing that
requires a **time-series of returns**: Sharpe, Sortino, VaR/CVaR, Calmar, equity-curve drawdown.

So new computation must land before 7A. The question this ADR settles is *where* it lives — folded
into the existing subsystems, or broken out — and which existing computation, if any, moves with it.

Two observations shape the decision:

1. **The existing economic math is misplaced.** `economic_metrics()` is pure portfolio analytics
   that lives in `calibration/gates.py` only because the gate consumes it. Economic measurement and
   confidence calibration are deliberately *separate* gates (the UI already renders them as distinct
   groups — `operational` / `calibration` / `economic`); they should be separate modules.
2. **The new metrics need a capability nothing currently provides** — a mark-to-market equity curve
   sampled over time. The risk/return ratios are otherwise ~10-line pure functions over that series.

---

## Decision

**A new top-level `analytics/` package owns derived risk/return measurement. The ledger keeps
source-of-truth state and any metric the risk engine needs synchronously.**

The dividing test: if the **risk engine or ledger needs it in real time to make a decision**
(sizing, the daily-loss breaker) it stays in the ledger as current-state; if it is a
**retrospective measurement over a sequence/series** for a gate or panel, it is analytics. By this
test `total_value` looks like analytics but is not — it gates every order — while `economic_metrics`
looks like it belongs by the gate but is pure measurement.

### What moves into `analytics/`

- **`economic_metrics()`** — moved whole from `calibration/gates.py`. It already takes a plain
  `Sequence[Decimal]`, so the move drags no coupling; `max_drawdown` rides along inside it.
  `calibration/gates.py` keeps `_economic_criteria()` (thresholds + pass/fail = gate *policy*),
  which now calls `analytics.economic_metrics(...)`. The `TradeBook` Protocol stays with the gate.
- **Fill-pairing P&L reconstruction** — extracted from `gateway/routes/portfolio.py` (`/trades`,
  the open→close pairing that re-derives realized P&L from `order.filled` events). The equity-curve
  projection needs the identical logic; extracting it now prevents three subtly-different copies of
  the P&L formula (route, equity curve, backtest attribution).

### What stays put

| Computation | Location | Why |
|---|---|---|
| `cash`, `positions`, `open/close_position`, fill handling | ledger | source of truth, state mutation |
| `total_value`, `unrealized_pnl`, `equity_contribution` | ledger | risk engine reads these **synchronously at sizing time** |
| `daily_realized_pnl` + rollover | ledger | the **daily-loss breaker** — live operational risk state |
| `realized_trades` / `daily_trades` | ledger | raw *facts* analytics consumes, not metrics |
| ECE, reliability buckets | calibration | north-star metric; kept separate from economic analytics by design |

### What gets added

| Metric | Needs |
|---|---|
| Sharpe, Sortino, return volatility | a periodic return series |
| VaR / CVaR | same return series |
| Calmar | Sharpe inputs + drawdown |
| Equity-curve drawdown (%, duration, underwater) | mark-to-market series over *time* |
| Per-instrument / per-mode P&L attribution | grouping over fills (cheap) |

Everything except the last collapses to **one new capability: a mark-to-market equity curve sampled
over time.**

### The equity curve is an event-time-keyed read-side projection

**No wall-clock timer.** Timer-based sampling does not fire during backtest replay and violates the
two-clock rule. The curve is computed **on demand as a projection over the event store** — exactly
as `/api/portfolio/trades` already reconstructs P&L from `order.filled` events. Daily marks come
from fills plus the last `market.tick` per instrument per day, keyed by `event_time`. No new event
type, no new stateful subscriber, replay-reproducible.

### Module shape

- `analytics/metrics.py` — pure, stateless: `sharpe`, `sortino`, `var`, `cvar`, `calmar`,
  `drawdown` (dollar + pct + duration), annualization helpers, and the moved `economic_metrics`.
- `analytics/equity_curve.py` — builds the daily mark-to-market series from event-store fills +
  last-tick-per-day; on-demand projection; event-time keyed.
- `gateway/routes/analytics.py` → `/api/analytics`.
- `GateTracker` consumes Sharpe so the **deferred gate line becomes a measured criterion** — the
  direct unblock for the Phase 7A entry gate.

Analytics reads the portfolio / event store through a narrow structural interface (as `GateTracker`
already reads the portfolio via `TradeBook`), never a hard import. It is read-side only: no changes
to producers or the bus.

---

## Consequences

### Positive
- The economic gate and the calibration gate are now separate modules, matching the two-gate
  separation the system already asserts conceptually and in the UI.
- The P&L-from-fills formula has one implementation shared by the route, the equity curve, and
  future backtest attribution, instead of drifting copies.
- The Sharpe entry-gate criterion becomes measurable, unblocking Phase 7A.
- The refactor (move `economic_metrics`, extract the P&L helper) is behavior-preserving and lands
  independently of the new return-series work — tests stay green at the seam.

### Negative / constraints
- The equity curve is recomputed from the event store per request rather than maintained
  incrementally. For a single operator this is cheap; if it ever becomes hot it can be memoized
  without changing the contract.
- Sharpe computed on paper today is net-of-fees but **not** net-of-slippage (slippage modeling is a
  Phase 7B realism item), so the measured value is not yet identical to the gate's
  "net of modeled fees + slippage" wording until 7B lands (see Open question 2).

---

## Alternatives considered

**Extend `calibration/` in place.** Rejected: calibration is the confidence north-star; folding
return/risk metrics into it blurs the deliberate economic-vs-calibration gate separation and grows a
module around a concern it does not own.

**Add the metrics to `portfolio/ledger.py`.** Rejected: the ledger is event-driven state mutation
and real-time risk state (the daily breaker, sizing reads). A retrospective time-series projection
is a different concern with a different lifecycle; co-locating them couples the hot sizing path to
reporting code.

**Maintain a live equity curve via a timer-based subscriber.** Rejected: a wall-clock sampler does
not reproduce under backtest replay and violates the two-clock rule. An on-demand event-time
projection is deterministic and adds no new bus state.

---

## Open questions

1. **Drawdown definition for the panel.** Keep the gate's realized-trade-curve drawdown *and* add an
   equity-curve drawdown (includes unrealized, has a time axis)? They are different numbers; the gate
   is fine with the former, the panel likely wants the latter.
   **Resolved (2026-06-16): both.** The gate is unchanged (still realized-trade drawdown in
   `economic_metrics`); `analytics.equity_drawdown` adds the equity-curve drawdown (value + %) for the
   panel and `/api/analytics`.
2. **Sharpe honesty.** Surface the fees-only paper Sharpe now with a caveat, or hold the gate
   criterion as `deferred` until Phase 7B adds slippage modeling?
   **Resolved (2026-06-16): keep deferred, show in panel.** Sharpe/Sortino are computed and displayed
   (caveated "net of fees, not slippage"); `gates.py` is untouched and the Sharpe criterion stays in
   the `deferred` list. It becomes a measured gate criterion only when 7B adds slippage.

---

## Relationship to other ADRs

- **ADR-001 (event bus):** analytics is a read-side projection over the persisted event store; it
  adds no event types and no producers.
- **ADR-010 (roadmap re-scope):** this enables the Phase 7A live-trading entry gate that ADR-010
  deferred behind the alternative-data phase.

---

## Sequencing

1. **Refactor (no behavior change):** create `analytics/`, move `economic_metrics` + extract the
   P&L-reconstruction helper, repoint `gates.py` and the `/trades` route. Tests stay green.
2. **New capability:** add `equity_curve.py` + the risk/return functions, the `/api/analytics`
   route and panel; promote the Sharpe gate criterion from deferred to measured (pending Open
   question 2).
