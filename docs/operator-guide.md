# Operator Guide

AFTERHOURS is a single-operator, own-capital trading terminal. It describes how the terminal behaves
**today**: what each autonomy mode actually does, how the kill
switch works, the path a decision takes from proposal to fill, and the
deterministic risk controls that sit between any decision and your capital.

It is deliberately text-first. The UI is still moving; screenshots would be
stale within a phase. They'll be added once the terminal layout freezes ahead
of live trading (Phase 7).

> **Scope (2026-06-29):** Phases 0–5 complete; **Phase 6A** (alt-data signal feeds) and **Phase 6B.1**
> (the disclosure-driven Discovery Engine, ADR-012 - the Discover workspace) are **live**; 6B.2
> (breadth scanner / crypto-primary / auto-add) is pending. The live-trading hardening blockers are
> cleared (all CRITICAL issues closed). Live trading is **Phase 7, staged 7A–7D**, starting with
> **7A micro-capital validation** (Assisted-only real orders at $250–500 via Alpaca, gated on the
> gateway auth/bind hardening and the [`pre-phase-7-risk-review.md`](pre-phase-7-risk-review.md)
> action list) - see [`phase-7-plan.md`](phase-7-plan.md). **Phase 7 is not started.** The only modes
> you can run right now are **Observe**, **Paper**, and **Assisted**, and all fills are simulated.
> There is **no live trading yet** - no real order ever reaches a venue. Semi-auto, Supervised, and
> the live execution adapter are Phase 7+ and are documented here only as a boundary, not as features
> you can use.

---

## 1. The terminal at a glance

The terminal is a single dark screen. The header carries the only global
controls; everything below it is read-only panels reducing the live event
stream.

**Header (left → right):**

- **AFTERHOURS** - brand mark. The header tints with the active mode.
- **Workspace switcher** - `Discover` · `Terminal` · `Review`. The panels are grouped into three
  workflow workspaces (below); the switcher chooses which group is on screen. On mobile this is a
  bottom tab bar.
- **Mode selector** - `OBSERVE` · `PAPER` · `ASSISTED` buttons. Clicking one
  requests the mode change; the highlighted button is the current mode.
- **HALT** - the kill switch. Always available. See §4.
- **Connection pip** - `live` (green) when the WebSocket is connected,
  `offline` (red) when it is reconnecting.

**Panels, by workspace:**

| Workspace | Panel | Shows |
| --- | --- | --- |
| **Discover** | **Discovery Feed** | Ranked *unwatched* candidates fused from multiple sources (confluence score + factor chips, expandable evidence), one-click add-to-watchlist, and a lazy "Analyze with AI" pass. The pre-watchlist funnel (6B.1). |
| **Discover** | **Watchlist** | The instruments the pipeline acts on; add/remove here. |
| **Terminal** | **Market Watch** | Live ticks for watched instruments (venue clock). |
| **Terminal** | **Signal Feed** | Incoming signals (price alerts, news, alt-data) per the watchlist. |
| **Terminal** | **Thesis Feed** | AI theses, with invalidations struck through. |
| **Terminal** | **Decision Queue** | Proposed/approved decisions; in Assisted mode this is where you approve or reject. |
| **Review** | **Portfolio** | Open positions, cash, and P&L (paper book). |
| **Review** | **Calibration** | ECE and the Appendix B reliability gates - how well-calibrated the AI's confidence has been. |
| **Review** | **Analytics** | Equity curve + risk/return metrics (Sharpe, Sortino, volatility, VaR, drawdown, net P&L) - the economic gate's read-side view. |

Any ticker symbol across the terminal is a click-to-chart link that jumps to the Discover workspace
and loads that symbol's price history. Panels rehydrate on load by replaying recent event history, so
a refresh never loses state.

---

## 2. Autonomy modes - the core concept

Autonomy is **graduated**. Each mode adds exactly one increment of authority
over the previous one. The full ladder is Observe → Paper → Assisted →
Semi-auto → Supervised; today you operate the first three.

The single most important thing to internalise: **the mode controls who pulls
the trigger, not whether the AI thinks.** The AI reasons and proposes in every
mode. The deterministic risk engine checks every proposal in every mode. What
changes between modes is what happens *after* a decision is approved.

| Mode | AI proposes? | Risk engine checks? | Fill happens… | Your role |
| --- | --- | --- | --- | --- |
| **Observe** | Yes | Yes (always rejects) | Never | Watch; build trust; read calibration |
| **Paper** | Yes | Yes | Automatically, simulated | Monitor; tune; review outcomes |
| **Assisted** | Yes | Yes | Only after you click execute, simulated | Approve/reject each order |

### Observe

A read-only shadow mode. The full pipeline runs - ticks, signals, theses,
proposals - but the risk engine rejects **every** decision with the reason
`observe_mode: shadow decision logged for calibration`. Nothing is parked,
nothing fills, the portfolio never moves.

The point of Observe is **calibration without risk**: shadow decisions are still
scored against what price actually did, so the Calibration panel fills in and
you learn whether the AI's confidence is trustworthy *before* you let it touch a
book. Start here with any new model, prompt, or instrument set.

### Paper

The full pipeline with **simulated fills**. When the risk engine approves a
decision, the paper executor fills it automatically - applying configured
slippage and fees - and the position lands in the paper portfolio. Stop-losses
are monitored live and close positions automatically when breached.

Paper is hands-off by design: you are evaluating the *whole system's* behaviour
end-to-end (does it size sensibly, do stops fire, is the P&L plausible), not
gating individual trades. Use it once Observe shows the AI is reasonably
calibrated and you want to see realised outcomes.

### Assisted

Same as Paper, except **every approved decision waits for you**. On approval the
executor *parks* the decision instead of filling it; it appears in the Decision
Queue. You then either:

- **Execute** it (Decision Queue → execute), or
- **Reject** it with a reason (captured as training signal).

Two safety behaviours matter here:

- **Parked decisions expire.** A parked decision has a TTL (default **1 hour**,
  `PORTFOLIO_PENDING_TTL_SECONDS`). After that it auto-expires with an audited
  `decision.expired` event and can no longer be executed - an approval from an
  hour ago no longer reflects the market.
- **Execution re-validates against *current* state.** When you click execute,
  the decision is re-run through the full pre-trade checks and its size and stop
  are recomputed from the current price. If the world has moved (you now hold the
  instrument, the daily-loss breaker has tripped, price ran through the old
  stop), the execution is refused as stale rather than filled on old
  assumptions.

Assisted is the closest analogue to how live trading will feel: the AI does the
analysis and sizing, you remain the final authority on every order.

### Switching modes

Use the header mode selector. Transitions are validated server-side - you move
between Observe/Paper/Assisted freely. Changing mode is itself an audited event.
Demoting below Assisted (or halting) immediately expires any parked decisions.

---

## 3. The decision lifecycle

Every dollar of risk traces back to a **Decision** object, which is immutable
once created - status changes are new events, never mutations, so the event log
is a complete audit trail.

```
market.tick ─► signal.created ─► thesis.created ─► decision.proposed
                                                         │
                                              risk engine evaluates
                                                         │
                                    ┌────────────────────┴───────────────────┐
                              decision.rejected                       decision.approved
                              (reason recorded)                              │
                                                          ┌──────────────────┴─────────────────┐
                                                    PAPER: auto                       ASSISTED: parked
                                                          │                            (you execute / reject
                                                          │                             / it expires)
                                                          ▼                                    │
                                                   order.submitted  ◄───────────────────────────┘
                                                          │
                                                   order.filled
                                                          │
                                          (held; stop-loss monitored on every tick)
                                                          │
                                                   order.filled (close)  ◄─ manual close or stop breach
                                                          │
                                                  decision.resolved (scored at horizon → calibration)
```

What the AI contributes vs. what the system computes:

- **The AI provides** only `reasoning`, `evidence[]` (each citing a real
  signal), `confidence`, and direction (instrument / side / time-horizon).
- **The system computes** `size_usd` and the risk verdict **deterministically**.
  The AI never sets position size. This is a hard invariant.

Each order carries a deterministic **client order ID** (`<decision_id>:open` or
`:close`), so a re-delivered approval or a re-fired stop can never produce a
duplicate fill - the same decision always maps to the same order.

---

## 4. The kill switch (HALT)

`HALT` is always available in the header and does one thing, decisively:
**forces the system to Observe.** It is wired directly into both the risk engine
and the executor, independent of the normal mode-change path, so it cannot be
missed or reordered.

On halt:

- The mode drops to **Observe** - all subsequent proposals are rejected.
- The Assisted pending queue is **flushed**: every parked decision is expired
  with an audited `decision.expired` event (nothing is silently dropped).
- The halt itself is recorded as a `risk.halt` event.

Halting never closes existing open positions - it stops *new* risk from being
taken. To flatten the book, close positions explicitly. After a halt you must
deliberately re-enter Paper or Assisted; the system never re-arms itself.

Note there is also an **automatic** safety stop independent of the button: if
realised losses cross the daily-loss limit (default 5%), the risk engine refuses
further entries for the rest of that day.

---

## 5. Risk controls - the deterministic gatekeeper

Every proposal passes through the risk engine before any capital (paper or, in
Phase 7, real) is committed. The AI cannot bypass it. A proposal is **rejected**
if any check fails; the reason is recorded on the decision.

Pre-trade checks, in order:

1. **Mode** - Observe rejects everything.
2. **Max open positions** - default **5** (`RISK_MAX_OPEN_POSITIONS`).
3. **No pyramiding** - rejected if you already hold the instrument.
4. **Daily loss breaker** - if today's realised loss ≥ **5%**
   (`RISK_MAX_DAILY_LOSS_PCT`) of the book, no new entries that day.
5. **Deterministic sizing** - size is derived from risk budget, not chosen by
   the AI:
   - risk **2%** of the book per trade (`RISK_MAX_TRADE_LOSS_PCT`),
   - capped at **5%** of the book per position (`RISK_MAX_POSITION_PCT`),
   - against a **3%** stop distance (`RISK_STOP_LOSS_PCT`).
   A book too small to size a real position is rejected.
6. **Mandatory stop** - a stop price is required. If there's no tick data yet to
   compute one, the decision is rejected (`no_stop_price`) rather than opening an
   unprotected position. The system never fails open into more risk.

After a position is open, the engine **monitors every tick** and closes the
position automatically when price breaches the stop (`risk.limit_breached` →
close fill).

Paper fills also model market friction: **0.1%** slippage and **0.1%** fee per
fill (`PORTFOLIO_SLIPPAGE_PCT`, `PORTFOLIO_FEE_PCT`); the paper book starts at
**$10,000** (`PORTFOLIO_INITIAL_CASH`).

All of these are defaults; each is overridable via its `.env` variable (see
`.env.example`). Modules read settings by `env_prefix` - `RISK_*` for the risk
engine, `PORTFOLIO_*` for the executor and book.

---

## 6. Common workflows

**Evaluate a new model or instrument set.**
Start in **Observe**. Add instruments to the Watchlist. Let proposals accumulate
and watch the **Calibration** panel - you want ECE low and the reliability gates
green before risking anything.

**Run a hands-off paper test.**
Switch to **Paper**. The system sizes, fills, and manages stops on its own.
Review the **Portfolio** panel for realised P&L and the resolved decisions for
whether outcomes matched confidence.

**Gate trades yourself.**
Switch to **Assisted**. Approved decisions appear in the **Decision Queue**.
Execute the ones you agree with; reject the rest *with a reason* (the reason is
training signal). Don't sit on them - they expire in an hour and re-validate on
execute.

**Stop everything now.**
Hit **HALT**. The system drops to Observe and clears the pending queue. Close
any open positions manually if you want a flat book.

---

## 7. What is *not* here yet (Phase 7 boundary)

So you don't go looking for them:

- **Live trading.** No real orders yet. All fills are simulated. API keys are
  read-only / withdrawal-disabled and the data feeds use only public endpoints.
  Live execution arrives in **Phase 7A** (Assisted-only, micro-capital, via
  Alpaca - paper→live parity, then Kraken in 7B; ADR-009). The first real order is
  gated on the gateway being authenticated and bound to localhost, and on the
  [`pre-phase-7-risk-review.md`](pre-phase-7-risk-review.md) action list (chiefly
  venue-resident stops and a real daily-loss brake). Full staged plan:
  [`phase-7-plan.md`](phase-7-plan.md).
- **Semi-auto and Supervised modes.** Defined in the model but not operable from
  the terminal. Semi-auto becomes operable in **Phase 7D** (bounded autonomous
  execution); Supervised is Phase 8. Both are meaningful only once live execution
  exists and has proven correct.

Outcome resolution, calibration reporting, and the backtest harness itself are all
live (Phase 4): replay a recorded event range with `python -m backtest` - see the
"Running a Backtest" section of `docs/development.md`.

When live trading lands, the order flow is already designed to share the same
`Order` structure and client-order-id idempotency, so going live is an additive
change - and this guide will grow a live-trading section (and screenshots) then.

---

*Authoritative sources behind this guide: `PLANNING.md` (phase roadmap and
non-negotiables), `docs/adr/` (design decisions), and the code in `risk/`,
`portfolio/`, and `gateway/routes/`. Where this guide and the code disagree, the
code wins - tell me and I'll fix the guide.*
