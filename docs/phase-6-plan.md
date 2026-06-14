# Phase 6 Plan — Live Trading, in four graduated sub-phases

> **⚠ Renumbered 2026-06-13 (ADR-010):** this is now the **Phase 7** plan — alternative-data
> ingestion was inserted as the new Phase 6. Sub-phases **6A–6D below are now 7A–7D**. The filename
> is retained to avoid breaking references; read every "Phase 6" in this document as "Phase 7".
>
> **Status:** Phases 0–5 complete. Pre-Phase-6 hardening's live-trading blockers are cleared
> (all CRITICAL `phase-6-blocker` issues closed, 2026-06-12). Phase 6 is **not yet started**; this
> document is the plan.
>
> **Authoritative companions:** `PLANNING.md` §9 (roadmap), Appendix B (autonomy gates),
> `docs/adr/009-live-execution-venue.md` (venue decision), `docs/pre-phase-6-issues.md`
> (remaining entry gate), `docs/operator-guide.md` (operator behaviour).

---

## Why Phase 6 is split

The original Phase 6 ("Live Trading — Assisted") bundled *building the live adapter* with
*proving it correct* and *scaling capital*. Those are different risk profiles and deserve
different gates. The hard part of going live is **not** the broker API — the architecture already
treats execution as a swappable adapter behind the `Order`/`client_order_id` contract. The hard
part is validating that the paper assumptions (fees, spreads, latency, slippage, thesis
persistence) survive contact with live markets, and that the order lifecycle is correct under real
acks, partial fills, rejects, cancels, and restarts.

So Phase 6 is staged: **prove correctness at trivial size → harden execution realism and add a
second venue → ramp capital under proven correctness → only then allow bounded autonomy.** Each
sub-phase ends in something trustworthy and gates the next. Capital does not increase until
correctness is boring.

The venue choice serves this directly (ADR-009): **Alpaca first**, because its paper API is
behaviourally identical to live, so the entire adapter is validated at zero capital risk before a
single real order. **Kraken** (already the primary market-data feed) is added as the second live
execution venue in 6B.

---

## Phase 6A — Micro-capital validation

**Goal:** prove the live execution path is correct and safe with real, trivial capital.
**Venue:** Alpaca (equities + crypto, fractional). **Mode:** Assisted only. **Capital:** $250–500.
**Duration:** 1–2 weeks of live runtime after the Alpaca-Paper dry run passes.

### Entry gates (all required before any live key is loaded)
- **Appendix B Paper → Assisted gate passed** — ≥100 paper trades over ≥14 days, ECE ≤ 0.12, 0 limit
  breaches, Sharpe > 0 net of modeled fees + slippage, kill-switch drill passed, recon clean.
- **Gateway hardened (single-operator local bar)** — the last open pre-Phase-6 item
  (`docs/pre-phase-6-issues.md`), scoped to what a local single-operator box actually needs:
  - **Bind `127.0.0.1`** — `GATEWAY_HOST` defaults to localhost, not `0.0.0.0`. This is the
    load-bearing fix: `0.0.0.0` exposes `/api/halt`, `/api/mode`, and `/api/decisions/{id}/execute`
    to **every device on the LAN**, so an unauthenticated halt endpoint means anyone on the network
    can silently disarm the kill switch. A one-line default change.
  - **Shared-secret token** on the state-changing routes (`halt`, `mode`, `execute`) and the WS
    endpoint — closes the browser CSRF / DNS-rebinding vector that can reach `localhost:8000` from
    any page the operator visits. An afternoon, not a project.
  - *Deferred to Phase 7+ (not a 6A gate):* full multi-route authentication, MFA console, and the
    "auth it like a bank" posture of PLANNING §6.4 — these matter only if the console ever leaves
    the operator's machine.
- **Keys provisioned per ADR-003** — Alpaca trade-scoped, **withdrawal-disabled**, never committed.

### Scope
- **`BrokerAdapter` ABC** parallel to `PaperExecutor`, sharing the existing `Order` structure and
  `client_order_id` (`<decision_id>:open|close`) idempotency. The risk engine and producers are
  untouched — execution is selected behind the adapter seam.
- **Alpaca adapter**, validated first against **Alpaca Paper** (identical API), promoted to live by
  swapping base URL + keys.
- **Real order state machine** — handle acknowledgement, partial fills, rejects, cancels, and
  terminal states, replacing the paper model's instant-full-fill assumption.
- **Reconciliation loop** — poll broker positions/orders and continuously compare to the internal
  ledger; any unexplained divergence raises a `reconciliation`-class alert and (per Appendix B
  demotion triggers) knocks the system down a mode.
- **In-flight recovery** — on restart, reconcile open broker orders/positions against the event log
  so no live order is silently lost or double-counted.
- **Assisted-only enforcement** — every live order is human-approved; the kill switch flushes
  pending and forces OBSERVE exactly as in paper.

### Exit checklist (the validation bar — all must hold over the live window)
- [ ] **Reconciliation perfect** — internal ledger matches broker ground truth at all times.
- [ ] **No duplicate orders** — `client_order_id` idempotency holds against re-delivery and re-fired stops.
- [ ] **No state-recovery bugs** — restart mid-flight recovers cleanly; no lost or phantom positions.
- [ ] **No stale-order execution** — TTL expiry + execute-time re-validation refuse stale approvals.
- [ ] **No risk-engine bypasses** — every live order passed the deterministic gate at execute time.
- [ ] **Live fills match assumptions** — realized fees, spread, latency, and slippage are within the
      modeled paper bands (or the model is updated in 6B with the measured reality).
- [ ] **Thesis persistence holds** — theses invalidate correctly against live data, no orphaned beliefs.

Only when this checklist is green does capital increase — and only via 6C.

---

## Phase 6B — Execution realism & second venue

**Goal:** harden the execution model against live microstructure and add Kraken crypto execution.
**Mode:** Assisted only. **Capital:** still micro (6A level).

### Scope
- **Kraken live crypto adapter** behind the same `BrokerAdapter` ABC; Kraken stays the primary
  market-data feed throughout. (Kraken has no paper endpoint and higher crypto minimums — hence it
  follows the Alpaca-validated path rather than leading it.)
- **Venue routing** — equity → Alpaca, crypto → Kraken or Alpaca, selected per instrument.
- **Recalibrate the friction model** — replace the paper defaults (0.1% slippage, 0.1% fee) with
  values fit from measured 6A live fills (per-venue fee tiers, observed slippage, latency).
- **Partial-fill accounting** hardened across venues; **per-venue reconciliation** loops.

### Exit
- Both venues reconcile cleanly under partial fills/rejects/cancels; the friction model reflects
  measured live costs; routing is correct per instrument.

---

## Phase 6C — Graduated capital ramp

**Goal:** increase position size in controlled steps, each gated on sustained correctness.
**Mode:** Assisted only.

### Scope
- **Stepwise capital increases** (e.g. doubling bands), each step gated on a clean reconciliation
  and breach-free window at the prior size before advancing.
- **Live limits re-tuned** for real capital — daily-loss breaker, max exposure, position caps
  re-evaluated against the live book rather than the $10k paper book.
- **Operational runbook** — funding/withdrawal procedure (keys stay withdrawal-disabled), key
  rotation, incident response, and lot/tax tracking.

### Exit
- The system runs reliably at the target operating size with live limits proven and an operational
  runbook in place.

---

## Phase 6D — Live semi-auto (bounded autonomous execution)

**Goal:** the first autonomous execution, tightly bounded — the bridge into Phase 7.
**Entry gate:** Appendix B **Assisted → Semi-auto** gate — ≥50 live assisted trades over ≥30 days,
ECE ≤ 0.10 and stable, 0 breaches, 0 reconciliation/idempotency errors, operator reject rate ≤ 25%,
net-positive after real costs, **execution envelope defined & tested**.

### Scope
- **Semi-auto mode** made operable from the terminal: the system executes within a tightly bounded
  envelope (size, frequency, instrument scope) without per-order approval; everything outside the
  envelope still requires the operator.
- Demotion triggers stay full-strength (PLANNING Appendix B) — calibration drift, drawdown breach,
  recon/idempotency error, model/prompt version change, or regime break drops it back to Assisted.

### Exit
- Bounded autonomous execution runs correctly and falls back to Assisted the instant the evidence
  turns — handing off to Phase 7 (full equities, Supervised mode, correlation risk, Strategy Lab,
  Postgres migration path).

---

## What does *not* change in Phase 6

- **Separation of duties.** The LLM still only proposes direction/reasoning/evidence/confidence; the
  deterministic risk engine still sets size and is the final gate, now in front of *real* capital.
- **The bus contract.** Live execution is an adapter swap; producers, the risk engine, and the UI
  are unchanged. `order.submitted → order.filled → decision.resolved` is the same flow with a real
  venue behind it.
- **Calibration over returns.** Promotion is still gated on ECE and the Appendix B criteria, not P&L.
- **Kill switch.** Always available; forces OBSERVE and flushes pending, now halting *real* risk.
