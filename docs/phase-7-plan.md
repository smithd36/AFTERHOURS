# Phase 7 Plan - Live Trading, in four graduated sub-phases

> **History:** this plan was originally written as "Phase 6" and was **renumbered to Phase 7 by
> ADR-010** (2026-06-13), which inserted alternative-data ingestion as the new Phase 6. The file was
> renamed `phase-6-plan.md` → `phase-7-plan.md` on 2026-06-29; all phase numbers below are now
> Phase 7 as written (no "read one higher" translation needed).
>
> **Status (2026-06-29):** Phases 0–5 , 6A (2026-06-15), 6B.1 (2026-06-16); 6B.2 pending.
> **Phase 7 is not yet started** - this document is the plan. The pre-live-trading hardening that
> gated 7A is **complete** (all CRITICAL correctness/durability blockers closed 2026-06-12). Two
> things remain before the first live key: the **gateway bind/auth hardening** (entry gate below) and
> the **money-loss action list** in [`pre-phase-7-risk-review.md`](pre-phase-7-risk-review.md).
>
> **Authoritative companions:** [`../PLANNING.md`](../PLANNING.md) §9 (roadmap), Appendix B
> (autonomy gates); [`adr/009-live-execution-venue.md`](adr/009-live-execution-venue.md) (venue
> decision); [`pre-phase-7-risk-review.md`](pre-phase-7-risk-review.md) (pre-live money-loss review);
> [`operator-guide.md`](operator-guide.md) (operator behaviour).

---

## Why Phase 7 is split

The original "Live Trading - Assisted" phase bundled *building the live adapter* with *proving it
correct* and *scaling capital*. Those are different risk profiles and deserve different gates. The
hard part of going live is **not** the broker API - the architecture already treats execution as a
swappable adapter behind the `Order`/`client_order_id` contract. The hard part is validating that the
paper assumptions (fees, spreads, latency, slippage, thesis persistence) survive contact with live
markets, and that the order lifecycle is correct under real acks, partial fills, rejects, cancels,
and restarts.

So Phase 7 is staged: **prove correctness at trivial size → harden execution realism and add a
second venue → ramp capital under proven correctness → only then allow bounded autonomy.** Each
sub-phase ends in something trustworthy and gates the next. Capital does not increase until
correctness is boring.

The venue choice serves this directly (ADR-009): **Alpaca first**, because its paper API is
behaviourally identical to live, so the entire adapter is validated at zero capital risk before a
single real order. **Kraken** (already the primary market-data feed) is added as the second live
execution venue in 7B.

---

## Phase 7A - Micro-capital validation

**Goal:** prove the live execution path is correct and safe with real, trivial capital.
**Venue:** Alpaca (equities + crypto, fractional). **Mode:** Assisted only. **Capital:** $250–500.
**Duration:** 1–2 weeks of live runtime after the Alpaca-Paper dry run passes.

### Entry gates (all required before any live key is loaded)
- **Appendix B Paper → Assisted gate passed** - ≥100 paper trades over ≥14 days, ECE ≤ 0.12, 0 limit
  breaches, Sharpe > 0 net of modeled fees + slippage, kill-switch drill passed, recon clean.
- **Pre-live money-loss review actioned** - the carry-over risks in
  [`pre-phase-7-risk-review.md`](pre-phase-7-risk-review.md) are resolved or explicitly accepted.
  The load-bearing ones: venue-resident stops, a real (realized+unrealized) daily-loss brake,
  long-only for 7A, and a slippage guard.
- **Gateway hardened (single-operator local bar)** - scoped to what a local single-operator box
  actually needs:
  - **Bind `127.0.0.1`** - `GATEWAY_HOST` currently defaults to `0.0.0.0`, which exposes
    `/api/halt`, `/api/mode`, and `/api/decisions/{id}/execute` to **every device on the LAN**, so an
    unauthenticated halt endpoint means anyone on the network can silently disarm the kill switch. A
    one-line default change.
  - **Shared-secret token** on the state-changing routes (`halt`, `mode`, `execute`) and the WS
    endpoint - closes the browser CSRF / DNS-rebinding vector that can reach `localhost:8000` from
    any page the operator visits. An afternoon, not a project.
  - *Deferred to Phase 8+ (not a 7A gate):* full multi-route authentication, MFA console, and the
    "auth it like a bank" posture of PLANNING §6.4 - these matter only if the console ever leaves
    the operator's machine.
- **Keys provisioned per ADR-003** - Alpaca trade-scoped, **withdrawal-disabled**, never committed.

### 7A readiness checklist

The carry-over money-loss risks from [`pre-phase-7-risk-review.md`](pre-phase-7-risk-review.md) (the
standing review holds the full findings; section refs below). Each must be **resolved or explicitly
accepted** before the first live key. Items 1–4 are load-bearing - they turn "the paper gate passed"
into "safe to risk real capital."

- [ ] **1. Venue-resident protective stops** - place a native stop / bracket (OCO) at Alpaca on
      entry so protection survives process death; the in-process tick monitor becomes secondary, not
      the only line of defence. (§1)
- [ ] **2. Real daily-loss brake** - compute the breaker against realized **+ unrealized** day P&L
      (or session equity drawdown) and, on breach, actually `halt()` (and optionally flatten) rather
      than only blocking new entries. (§2)
- [ ] **3. Long-only for 7A** - gate `side` by venue capability (Alpaca crypto is spot-only; equity
      shorts need borrow/margin) and keep untradeable shorts out of the paper book that seeds the
      gate. (§4)
- [ ] **4. Slippage guard** - use marketable-limit orders with a max-slippage bound instead of naked
      market orders; reject/hold when the spread exceeds the cap. Pairs with the liquidity admission
      floor (item 9). (§6)
- [ ] **5. Venue trading-rule validation** - validate min notional / lot size / fractionability
      before submit; reject (don't silently round) when sizing can't be honored. (§5)
- [ ] **6. Durable idempotency** - pass `client_order_id` to Alpaca for server-side dedup **and**
      rebuild the local `_submitted_orders` set from the audit log on restart. (§3)
- [ ] **7. Halt & flatten** - add an explicit "halt & flatten" operator action distinct from the
      read-only HALT; document precisely what HALT does and does not do. (§8)
- [ ] **8. Close the security entry-gate** - bind `127.0.0.1` + shared-secret token on the
      state-changing routes and WS, before any live key (also the gateway-hardening entry gate
      above). (§10)
- [ ] **9. Liquidity admission floor + ADV-% size cap** - add a basic min-ADV / max-spread admission
      floor and a cap on position size as a % of average daily volume to the risk engine (it is
      liquidity-blind today); the live-safety subset of 6B.2, pulled forward so the slippage guard
      (item 4) can actually fill. The breadth scanner / crypto-primary / auto-add stay in 6B.2. (§11)

### Scope
- **`BrokerAdapter` ABC** parallel to `PaperExecutor`, sharing the existing `Order` structure and
  `client_order_id` (`<decision_id>:open|close`) idempotency. The risk engine and producers are
  untouched - execution is selected behind the adapter seam.
- **Alpaca adapter**, validated first against **Alpaca Paper** (identical API), promoted to live by
  swapping base URL + keys.
- **Real order state machine** - handle acknowledgement, partial fills, rejects, cancels, and
  terminal states, replacing the paper model's instant-full-fill assumption.
- **Venue-resident protective stops** - place a native stop / bracket order at the venue on entry so
  protection survives process death, rather than relying solely on the in-process tick monitor
  (`pre-phase-7-risk-review.md` §1).
- **Reconciliation loop** - poll broker positions/orders and continuously compare to the internal
  ledger; any unexplained divergence raises a `reconciliation`-class alert and (per Appendix B
  demotion triggers) knocks the system down a mode.
- **In-flight recovery** - on restart, reconcile open broker orders/positions against the event log
  so no live order is silently lost or double-counted; pass `client_order_id` to Alpaca for
  server-side dedup and rebuild the local dedup set from the audit log.
- **Assisted-only enforcement** - every live order is human-approved; the kill switch flushes
  pending and forces OBSERVE exactly as in paper.

### Exit checklist (the validation bar - all must hold over the live window)
- [ ] **Reconciliation perfect** - internal ledger matches broker ground truth at all times.
- [ ] **No duplicate orders** - `client_order_id` idempotency holds against re-delivery and re-fired stops.
- [ ] **No state-recovery bugs** - restart mid-flight recovers cleanly; no lost or phantom positions.
- [ ] **No stale-order execution** - TTL expiry + execute-time re-validation refuse stale approvals.
- [ ] **No risk-engine bypasses** - every live order passed the deterministic gate at execute time.
- [ ] **Live fills match assumptions** - realized fees, spread, latency, and slippage are within the
      modeled paper bands (or the model is updated in 7B with the measured reality).
- [ ] **Thesis persistence holds** - theses invalidate correctly against live data, no orphaned beliefs.

Only when this checklist is green does capital increase - and only via 7C.

---

## Phase 7B - Execution realism & second venue

**Goal:** harden the execution model against live microstructure and add Kraken crypto execution.
**Mode:** Assisted only. **Capital:** still micro (7A level).

### Scope
- **Kraken live crypto adapter** behind the same `BrokerAdapter` ABC; Kraken stays the primary
  market-data feed throughout. (Kraken has no paper endpoint and higher crypto minimums - hence it
  follows the Alpaca-validated path rather than leading it.)
- **Venue routing** - equity → Alpaca, crypto → Kraken or Alpaca, selected per instrument.
- **Recalibrate the friction model** - replace the paper defaults (0.1% slippage, 0.1% fee) with
  values fit from measured 7A live fills (per-venue fee tiers, observed slippage, latency).
- **Partial-fill accounting** hardened across venues; **per-venue reconciliation** loops.

### Exit
- Both venues reconcile cleanly under partial fills/rejects/cancels; the friction model reflects
  measured live costs; routing is correct per instrument.

---

## Phase 7C - Graduated capital ramp

**Goal:** increase position size in controlled steps, each gated on sustained correctness.
**Mode:** Assisted only.

### Scope
- **Stepwise capital increases** (e.g. doubling bands), each step gated on a clean reconciliation
  and breach-free window at the prior size before advancing.
- **Live limits re-tuned** for real capital - daily-loss breaker, max exposure, position caps
  re-evaluated against the live book rather than the $10k paper book.
- **Operational runbook** - funding/withdrawal procedure (keys stay withdrawal-disabled), key
  rotation, incident response, and lot/tax tracking.

### Exit
- The system runs reliably at the target operating size with live limits proven and an operational
  runbook in place.

---

## Phase 7D - Live semi-auto (bounded autonomous execution)

**Goal:** the first autonomous execution, tightly bounded - the bridge into Phase 8.
**Entry gate:** Appendix B **Assisted → Semi-auto** gate - ≥50 live assisted trades over ≥30 days,
ECE ≤ 0.10 and stable, 0 breaches, 0 reconciliation/idempotency errors, operator reject rate ≤ 25%,
net-positive after real costs, **execution envelope defined & tested**.

### Scope
- **Semi-auto mode** made operable from the terminal: the system executes within a tightly bounded
  envelope (size, frequency, instrument scope) without per-order approval; everything outside the
  envelope still requires the operator.
- Demotion triggers stay full-strength (PLANNING Appendix B) - calibration drift, drawdown breach,
  recon/idempotency error, model/prompt version change, or regime break drops it back to Assisted.

### Exit
- Bounded autonomous execution runs correctly and falls back to Assisted the instant the evidence
  turns - handing off to Phase 8 (full equities, Supervised mode, correlation risk, Strategy Lab,
  Postgres migration path).

---

## What does *not* change in Phase 7

- **Separation of duties.** The LLM still only proposes direction/reasoning/evidence/confidence; the
  deterministic risk engine still sets size and is the final gate, now in front of *real* capital.
- **The bus contract.** Live execution is an adapter swap; producers, the risk engine, and the UI
  are unchanged. `order.submitted → order.filled → decision.resolved` is the same flow with a real
  venue behind it.
- **Calibration over returns.** Promotion is still gated on ECE and the Appendix B criteria, not P&L.
- **Kill switch.** Always available; forces OBSERVE and flushes pending, now halting *real* risk.
