# Pre-Phase-7 Money-Loss Review

> **Scope:** a focused sweep of the carry-over code paths (risk engine, executor, ledger, mode
> control, autonomy gate) for technical issues that could cause **loss of real capital** once the
> `BrokerAdapter` + Alpaca live execution lands in Phase 7 (`phase-7-plan.md`).
>
> **Context:** the home-server paper `afterhours.db` is near passing the Appendix B
> Paper → Assisted gate. This review is the "before we wire real money" pass. It is **not** a
> general code review - every finding is scored by its capital-loss potential live.
>
> **Status legend:** Critical (can lose money directly / silently) · High · Medium · Note.
> **Plan coverage:** whether `phase-7-plan.md` (the Phase 7 plan) already names the issue.
> "Under-specified" = the plan gestures at the area but not at this specific failure mode.

The headline: **the architecture's separation of duties is sound and the kill switch / mode model
is careful.** The risks below are almost all about the gap between the *paper executor's idealized
fill model* and *live market microstructure* - exactly the gap Phase 7A exists to close, but several
of these are latent in code that will carry straight into the live adapter and aren't called out in
the current plan.

---

## 1. Stops are synthetic (software-side), not resting orders at the venue

**Where:** `risk/engine.py:232-267` (`_handle_tick` stop monitor) → `RISK_LIMIT_BREACHED` →
`portfolio/executor.py:401-404` (`_handle_stop` → market close).

**What:** the stop-loss is enforced by an in-process loop that watches ticks and *then* sends a
market close. There is no protective order resting at the broker. The position's only protection is
**a running Python process on the Raspberry Pi.**

**Why it loses money live:**
- **Process/host death = unprotected position.** Power loss, network drop, an unhandled exception,
  a crash, or a redeploy leaves every open position with *zero* downside protection until the
  process is back. The restart path rehydrates positions and re-enforces stops *eventually*
  (`gateway/app.py:251`), but a `position`-horizon trade (21 days, `CALIBRATION_HORIZON_POSITION_DAYS`)
  can sit open for days while the box is down.
- **Stop granularity = tick cadence.** The equity feed polls once per `EQUITY_POLL_INTERVAL_SECONDS`
  (default **60s**). An equity stop is therefore only evaluated once a minute - a fast move blows
  far through the stop before the next poll. The synthetic close then fills at the *next* observed
  price, not the stop price.
- The paper close models a guaranteed fill at `price·(1 ± slippage)` (`executor.py:249-255`). Live,
  a gap-through stop fills wherever the book is - potentially well past the stop.

**Recommendation:** at entry, place a **native stop (or bracket/OCO)** order at Alpaca so protection
is venue-resident and survives process death. Treat the in-process monitor as a *secondary* trigger,
not the primary. This is the single highest-leverage change before going live.

**Plan coverage:** Under-specified. The plan lists a "real order state machine (acks, partials,
rejects, cancels)" but does **not** say protective stops must rest at the venue. Add it to 7A scope.

---

## 2. The daily-loss circuit breaker never halts and never sees unrealized losses

**Where:** `risk/engine.py:131-137`; `risk/settings.py:31` (`max_daily_loss_pct = 0.05`, commented
"→ auto-halt"); `portfolio/ledger.py:199-209` (`daily_realized_pnl`).

**What:** the "5% daily loss → auto-halt" described in settings/README is **not implemented**. The
breaker only:
1. fires on **realized** P&L (`daily_realized_pnl`), so open-position drawdown is invisible to it; and
2. on breach, only **rejects new proposals** - it does not halt, does not demote, does not flatten.

**Why it loses money live:**
- A book fully deployed across up to `max_open_positions` (5) positions can be deep in **unrealized**
  drawdown while the breaker reads **0%** (nothing has been closed). It will keep approving new
  entries into a falling market.
- Even once realized losses exceed 5%, the only effect is "no new trades." Existing losers keep
  running with no portfolio-level brake. There is no equity-drawdown halt anywhere
  (`grep` for `drawdown` in `risk/` finds only comments).

**Recommendation:** (a) compute the breaker against realized **+ unrealized** day P&L (or a
session equity-drawdown vs. start-of-day equity); (b) on breach, actually call
`ModeController.halt()` and optionally flatten, rather than only rejecting. Re-tune the threshold
against live capital in 7C, but wire the *mechanism* before 7A.

**Plan coverage:** Under-specified. 7C mentions "daily-loss breaker re-tuned for real capital,"
but the gap here is that the breaker is realized-only and toothless *today*, independent of tuning.

---

## 3. Order idempotency is in-memory only - it does not survive a restart

**Where:** `portfolio/executor.py:93` (`_submitted_orders: set[str]`), populated only in `_submit`
(`:455-460`). Nothing in `gateway/app.py` startup rehydrates it; `portfolio.rehydrate` replays
*fills into the ledger* but not the executor's dedup set.

**What:** `client_order_id` (`<decision_id>:open|close`) dedup is reconstructed from nothing on every
boot. After a restart the set is empty.

**Why it loses money live:** the deterministic `client_order_id` is the right design, but the local
set being volatile means the **only** durable duplicate-suppression has to be the venue. If the
process dies between "submit to venue" and "record fill," then on restart the local guard is gone and
nothing in *our* code prevents a re-submit of the same economic order.

**Recommendation:** two-part - (a) the Alpaca adapter **must** pass `client_order_id` to Alpaca,
which dedupes server-side (this is the real safety net; lean on it explicitly); and (b) rebuild
`_submitted_orders` from the audit log (`order.submitted` / `order.filled` `client_order_id`s) at
startup so the local guard is also restored. Today neither happens.

**Plan coverage:** Partially - 7A's "in-flight recovery / reconcile open orders against the event
log" covers the spirit. Make the two concrete actions above explicit; the current code does neither.

---

## 4. No shortability / direction-feasibility check - and untradeable shorts pollute the gate

**Where:** `risk/engine.py:171-178` sizes a `short` identically to a `long`;
`portfolio/executor.py:471-548` "fills" either direction unconditionally.

**What:** the LLM proposes `side`; nothing checks whether a short is actually executable on the
target venue.

**Why it loses money / corrupts the go-live decision:**
- **Alpaca crypto is spot-only - it cannot be shorted.** A `short` BTC-USD decision is unfillable
  live; the paper book "fills" it anyway.
- **Equity shorts** need a margin account + locatable/easy-to-borrow shares; at the planned
  $250–500 micro-capital with fractional sizing, shorting is largely unavailable, and many small-caps
  are hard-to-borrow.
- Because the paper executor fills shorts frictionlessly, the **realized-trade series that feeds the
  economic gate** (`calibration/gates.py:188-231`, reading `portfolio.realized_trades`) includes
  trades that **could never have executed live**. The gate the operator is about to act on is
  partly measuring fictional performance.

**Recommendation:** for 7A, constrain to **long-only** (or gate `side` by venue capability), and
ideally exclude untradeable shorts from the paper book so gate evidence reflects what's actually
executable. At minimum, reject short proposals at the risk engine when the venue can't support them.

**Plan coverage:** Not mentioned.

---

## 5. No venue trading-rule validation (min notional, lot/tick size, fractionability)

**Where:** `portfolio/executor.py:508` - `quantity = (size_usd / fill_price).quantize(1e-8)` with no
downstream venue-rule check.

**What:** quantity is computed purely from notional/price to 8 decimals. There is no check against
min order size, min notional, whole-share-only (non-fractionable) symbols, or crypto lot increments.

**Why it loses money / breaks live:** Alpaca rejects orders that violate its rules (e.g. 0.3 shares
of a non-fractionable symbol; sub-$1 notional; crypto below the per-asset minimum). A naive adapter
that rounds to satisfy the venue silently changes the size the risk engine computed - breaking the
"deterministic sizing is authoritative" invariant. Unhandled rejects can also leave the ledger
believing it holds a position the venue never opened (→ reconciliation divergence, → a "close" of a
phantom position).

**Recommendation:** the adapter must fetch/validate against venue trading rules pre-submit, and
reject (not silently round) when sizing can't be honored. `min_trade_size_usd` ($10) helps but is not
venue-aware.

**Plan coverage:** Under-specified (folded into "real order state machine"); worth an explicit
checklist item - fill-realism band in 7B won't catch outright rejects.

---

## 6. Naked market orders with no max-slippage guard

**Where:** `portfolio/executor.py:499-507` - fill modeled at `price·(1 ± 0.001)`; the live adapter
will send a market order at this seam.

**What:** there is no cap on how far a fill may deviate from the observed price, and no marketable-
limit alternative.

**Why it loses money live:** a market order into a thin book (low-liquidity name, off-hours, a
news-driven dislocation) can fill catastrophically far from the last tick. The 0.1% paper slippage
is a fiction for thin instruments. The system has **no liquidity admission floor** today (the floor
+ ADV-% cap are pulled forward from 6B.2 to 7A - see §11), so it can already propose trades in names
with no depth.

**Recommendation:** use **marketable limit orders** with a max-slippage bound (limit =
`price·(1 + cap)`), and reject/hold when the spread exceeds the cap. Pairs naturally with the
liquidity admission floor (§11), now also pulled forward to 7A.

**Plan coverage:** 7B recalibrates the friction *model*; it doesn't add a slippage *guard*.

---

## 7. Corporate actions, borrow fees, and financing are unmodeled (equity drift)

**Where:** ledger fee model is a flat `fee_pct` (`portfolio/settings.py:18-19`); no handling of
splits, dividends, short-borrow fees, or overnight financing anywhere.

**Why it matters live:** an equity split silently corrupts `quantity`/`entry_price` and every
subsequent P&L and stop calc; dividends and short-borrow/financing costs accrue real cash effects
the ledger never sees. These are concrete reconciliation-divergence sources the recon loop must
expect (and a `position`-horizon hold of 21 days is long enough to cross an ex-div or split).

**Recommendation:** in 7A reconciliation, treat broker position/cash as ground truth and re-base on
divergence; document corporate-action handling in the 7C operational runbook (already listed there
at a high level - make splits/dividends explicit).

**Plan coverage:** Reconciliation is in 7A; the specific drivers aren't enumerated.

---

## 8. HALT does not flatten - and combined with synthetic stops, leaves real exposure

**Where:** `core/mode.py:87-107` (`halt` forces OBSERVE + flushes pending); positions are left open.

**What:** the kill switch stops *new* activity and clears the parked queue, but open positions
remain and are managed only by the synthetic stop monitor (#1). Stop and thesis-invalidation closes
*do* still run in OBSERVE (those paths aren't mode-gated - good), but there is no "get me flat now."

**Why it matters live:** an operator hitting HALT during a fast crash likely expects to be flat.
Instead, real positions stay on, protected only by a software stop evaluated at tick cadence.

**Recommendation:** offer an explicit **"halt & flatten"** operator action (market-close all
positions), distinct from the read-only HALT. At minimum, document precisely what HALT does and does
not do in the operator guide.

**Plan coverage:** Not mentioned (the plan says HALT "forces OBSERVE and flushes pending" - which
is the current, non-flattening behavior).

---

## 9. Sizing runs off marks that can be stale (esp. after restart / market-closed)

**Where:** `risk/engine.py:120` sizes against `portfolio.total_value`, which marks open positions at
last tick; `portfolio/ledger.py:122-143` `seed_prices` seeds the **last persisted tick**, which over
a weekend/holiday can be days old.

**Why it matters live:** the next position is sized off a possibly-stale book value, and the
affordability gate (`engine.py:158-161`) trusts `cash` that, for shorts, was debited under the paper
**full-margin** model (`ledger.py:264`, `models.py:31-40`) - which is *not* how Alpaca buying power
works. Buying-power/margin must be checked **venue-side** before submit, not inferred from the
paper ledger.

**Recommendation:** gate sizing on mark freshness (reject/de-rate when the last tick is older than a
threshold); for live, source buying power from the broker, not the ledger.

**Plan coverage:** Under-specified.

---

## 10. Reconfirm the still-open security entry-gate before any live key

**Where:** `gateway/settings.py:15` - `GATEWAY_HOST` still defaults to `0.0.0.0`.

This is already the named 7A entry gate (`phase-7-plan.md` §7A entry gates), but flagging it
here because it is a **direct path to financial loss**: on `0.0.0.0`, `/api/halt`, `/api/mode`, and
`/api/decisions/{id}/execute` are reachable, unauthenticated, by **every device on the LAN** - anyone
can disarm the kill switch or execute a parked order. Bind `127.0.0.1` and add the shared-secret
token on state-changing routes **before** the first live key, exactly as the plan states. Confirmed
still open as of this review.

**Plan coverage:** Explicit 7A entry gate - verifying it's not yet done.

---

## 11. No liquidity admission floor or ADV participation cap - the risk engine is liquidity-blind (pulled forward from 6B.2)

**Where:** `risk/engine.py:120-181` sizing path - size is computed from notional / volatility /
portfolio value with **no** input for an instrument's tradable depth: no spread check, no minimum
average-daily-volume (ADV) admission floor, and no cap on position size as a % of ADV.

**What:** the engine sizes a position in any watched instrument identically whether it trades
millions a day or a few thousand dollars. Two controls - a **liquidity admission floor** (don't
trade names below a depth / ADV threshold) and an **ADV-% participation cap** (never take a position
larger than a set % of average daily volume) - were scoped to **6B.2** as discovery-growth
guardrails. They are also live-safety controls, and 6B.2 is **not** a prerequisite for 7A, so unless
they are pulled forward the first real capital can flow into names the engine has no depth
information about.

**Why it loses money live:**
- **Thin-name entry/exit.** A position in a low-ADV name can't be exited near the mark. The
  slippage guard (§6) caps a single order's price deviation, but if there is simply no depth, a
  bounded-slippage order won't fill and the synthetic stop (§1) can't get you out at the stop. The
  floor is the *structural* pair to §6's order-level guard.
- **Outsized positions you can't unwind.** With no ADV-% cap, the deterministic sizer can compute a
  notional that is a large fraction of a small name's daily volume - a position that moves the market
  against you on the way out and can't be flattened on a HALT (§8).
- **The gate is measuring fictional liquidity.** As with §4, the paper book fills these
  frictionlessly, so trades in names that are untradeable-at-size still feed the economic gate the
  operator is about to act on.

**Recommendation:** add a basic **liquidity admission floor** (reject proposals in instruments below
a min-ADV / max-spread threshold) and an **ADV-% size cap** (clamp `size_usd` so the position stays
under a configured % of average daily volume) to the risk engine before 7A. These are the
live-safety subset of 6B.2; the breadth scanner, crypto-primary unlock, and auto-add control plane
stay in 6B.2 (they widen the universe, they don't protect capital).

**Plan coverage:** Now a 7A readiness item (was 6B.2). §6 references it as the structural pair to
the slippage guard.

---

## What's solid (so we don't regress it)

- **Separation of duties holds.** The LLM never sets size; the risk engine is the final gate and
  recomputes size/stop at execute time for parked decisions (`executor.py:186-193`). Keep this seam
  intact when the adapter lands.
- **Mode is a single source of truth and never persisted** - every restart begins in OBSERVE
  (`core/mode.py`), so a crash can't silently resume live trading. Good fail-safe.
- **Mandatory stop at entry** - a proposal with no computable stop is rejected, not opened naked
  (`engine.py:168-181`).
- **Idempotent `client_order_id` design** and audited expiry/rejection events give the live adapter
  a correct contract to build on (the gap is durability, #3, not design).
- **Event-time everywhere** keeps backtest replay honest; the daily breaker and TTL run on the event
  clock, not the wall clock.

---

## Pre-7A action list

The prioritized, trackable version of this list lives as the **7A readiness checklist** in
[`phase-7-plan.md`](phase-7-plan.md) - that is the single place it's tracked. This document remains
the standing review: the detailed findings (§1–§10 above) are the *why* behind each checklist item.

The four load-bearing items - venue-resident stops (§1), a real realized+unrealized daily-loss
brake (§2), long-only for 7A (§4), and a slippage guard (§6) - are what turn "the paper gate passed"
into "safe to risk real capital." The liquidity admission floor + ADV-% participation cap (§11) are
pulled forward from 6B.2 to back the slippage guard - without depth admission, a bounded-slippage
order in a thin name simply won't fill. The paper book passing Appendix B is *necessary but not
sufficient*, because the paper executor's fills are frictionless and always succeed. The 7A exit
checklist's "live fills match assumptions" is the real bar.
