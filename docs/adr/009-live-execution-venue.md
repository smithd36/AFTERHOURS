# ADR-009: Live Execution Venue — Alpaca (primary) + Kraken (secondary)

**Status:** Accepted
**Date:** 2026-06-12
**Deciders:** Operator, Lead Architect
**Supersedes:** the "Coinbase Advanced Trade is the standing candidate" execution-venue note in ADR-007 (and PLANNING §12 decision #2). Market-data sourcing is unchanged: Kraken primary, Coinbase secondary.

> **Numbering note (post–ADR-010):** this ADR predates the roadmap re-scope. Its "Phase 6A/6B"
> refer to the **live-trading** sub-phases, now **7A/7B**. Under the current scheme "6B" is the
> Discovery Engine (ADR-012). Read live-execution phase numbers here one higher.

---

## Context

ADR-007 settled **market data** (Kraken primary, Coinbase secondary) but deliberately left the live **execution** venue to be committed "at the start of Phase 6," carrying Coinbase Advanced Trade as the standing candidate. Phase 6 is now being broken into sub-phases (see `docs/phase-6-plan.md`), and 6A is a **correctness-and-safety validation pass** with real but trivial capital ($250–500, Assisted-only). That goal — prove the live order path is correct before size matters — changes what we want from a first execution venue.

Three properties dominate the 6A choice:

1. **Paper↔live parity.** The single biggest de-risking lever for a validation phase is the ability to exercise the *entire* live adapter (submit → ack → partial fill → fill → reconcile → recover-on-restart) against a paper endpoint that is behaviourally identical to live, then promote with a credential swap.
2. **Micro-size accessibility.** At $250–500, fractional-share / low-minimum support is required to hold a diversified-enough book to validate sizing and reconciliation.
3. **One adapter, one reconciliation path** across the asset classes we actually watch (crypto + equities).

Against those:

- **Alpaca** exposes a paper-trading API that is byte-for-byte identical to live — same SDK, same order/fill objects, same `client_order_id` semantics — differing only by base URL and key. It supports **fractional shares** and covers **US equities and crypto** under one adapter. This is a near-ideal 6A venue.
- **Kraken** is already our primary crypto market-data feed (no auth, ADR-005) and a solid live crypto execution venue, but it has **no paper endpoint** and **higher crypto order minimums** — both work against a clean first correctness pass.
- **Coinbase Advanced Trade** (the ADR-007 standing candidate) offers no parity advantage over Alpaca, its auth wiring was never exercised for execution, and keeping it as the execution pick would mean validating an unproven path first.

## Decision

1. **Alpaca is the primary live execution venue.** Phase 6A validates the broker adapter against **Alpaca Paper** (zero capital risk), then promotes to live by swapping credentials. Alpaca covers both micro-size US equities (fractional shares) and crypto under a single adapter and reconciliation loop.
2. **Kraken is the secondary live execution venue, added in Phase 6B** for live crypto. Kraken remains the **primary market-data source** throughout (ADR-005, ADR-007) regardless of its execution role.
3. **Coinbase Advanced Trade is retired as the execution candidate.** Coinbase stays integrated as a **secondary market-data feed** only (ADR-007 unchanged on that point); it is no longer on the execution roadmap.
4. **The adapter contract is venue-neutral.** A `BrokerAdapter` ABC (parallel to `PaperExecutor`, sharing the same `Order` structure and `client_order_id` idempotency already in place) is the seam; Alpaca and Kraken are implementations selected per instrument by the existing `FeedRouter`-style routing (equity → Alpaca, crypto → Kraken or Alpaca). Adding a venue is an add, not a rewrite — mirroring the feed/store adapter pattern.

## Consequences

### Positive
- 6A can validate the live order lifecycle end-to-end with **no capital at risk** (Alpaca Paper), then go live with a credential swap — the validation phase's exit criteria (perfect reconciliation, no duplicate orders, no stale/stuck state, no risk-engine bypass, live fills matching paper assumptions) are testable before real money and re-confirmed with micro real money.
- Fractional shares make a $250–500 book meaningful for equities; one adapter spans both asset classes.
- The venue-neutral `BrokerAdapter` keeps the door open to re-adding Coinbase or any CCXT venue later without touching producers or the risk engine.

### Negative / constraints
- We now maintain **two** execution integrations (Alpaca + Kraken) by end of 6B, with per-venue reconciliation and partial-fill semantics to validate independently.
- Kraken-side crypto minimums may constrain the very smallest 6A trades — which is precisely why Kraken is deferred to 6B rather than carried in the first pass.
- Trade-scoped, withdrawal-disabled keys for **two** venues must be provisioned and hardened (ADR-003) before live keys are loaded; the gateway auth + bind hardening is the hard entry gate for 6A regardless of venue.

## When to revisit
- If Alpaca's paper environment diverges materially from live behaviour (fills, latency, partial-fill modelling), re-evaluate whether paper parity still justifies Alpaca-first.
- At 6B kickoff: confirm Kraken trade-API order semantics (minimums, post-only, fee tiers) against the recalibrated slippage/latency model built from 6A live fills.
- Revisit ADR-003 key permissioning for trade scope on **both** venues before live keys are loaded.

## Related
- ADR-003 (API-key security — read-only / withdrawal-disabled / never committed; trade-scope review due before live keys).
- ADR-005 (exchange feed architecture — Kraken WS v2, no auth, primary data).
- ADR-007 (roadmap re-scope; market-data venue settled, execution venue deferred to here).
- `docs/phase-6-plan.md` (the 6A–6D breakdown this venue choice serves).
