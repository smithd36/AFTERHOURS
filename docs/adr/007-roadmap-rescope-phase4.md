# ADR-007: Roadmap Re-scope — Backtest & Calibration Before Live Trading; Kraken Confirmed Primary

**Status:** Accepted
**Date:** 2026-06-09
**Deciders:** Operator, Lead Architect

---

## Context

Phase 3 (risk engine + paper trading) is complete. The original roadmap (PLANNING §9, v0.1) bundled three deliverables into a single Phase 4: the backtesting engine, calibration reporting, and the live broker adapter with assisted live trading.

Two problems with that bundle:

1. **Calibration evidence is a *prerequisite* for live trading, not a sibling deliverable.** The Appendix B autonomy gates require 50 resolved shadow decisions (ECE ≤ 0.18) to enter Paper and 100 paper trades over ≥ 14 days (ECE ≤ 0.12, zero limit breaches, kill-switch drill passed) before the first real dollar. The pipeline only began producing decisions in volume at the end of Phase 3, so the sample is effectively zero. Building the live adapter in the same phase as the instruments that gate its use invites pressure to go live before the evidence exists.
2. **The venue re-confirmation deferred in PLANNING §12 was due before Phase 4.** Phases 1–3 were built on Kraken WebSocket v2 (no auth required — see ADR-005), so Kraken is the proven feed while Coinbase auth wiring was never exercised.

## Decision

1. **Phase 4 is re-scoped to backtesting + calibration only** (including decision outcome resolution, which both depend on). No live trading, no exchange API keys, no real money in Phase 4.
2. **Live trading becomes a new Phase 5** — live broker/exchange adapter, Assisted mode only, micro position sizes — entered only after the Phase 4 calibration engine shows the Appendix B Paper → Assisted gates are passed.
3. **Subsequent phases shift down:** former Phase 5 (Scale & Autonomy) → Phase 6; former Phase 6 (Harden & Extend) → Phase 7.
4. **Kraken public endpoints are confirmed as the primary market-data source** (re-confirming the working arrangement of ADR-005 as the deliberate choice). **Coinbase remains integrated as the secondary source** — `ingestion/coinbase/` is kept complete and wired-ready, with auth deferred to Phase 5. The live *execution* venue (Coinbase Advanced Trade is the standing candidate) is committed at the start of Phase 5.

## Consequences

### Positive
- Phase 4 needs no exchange API keys at all — the no-secrets posture of Phases 0–3 extends through Phase 4.
- The calibration engine is built and accumulating evidence *before* anything can act on it, matching the "autonomy is earned" doctrine (PLANNING §5, §11).
- The Phase 5 live-adapter work starts with calibration data in hand to justify (or veto) going live.

### Negative / constraints
- Real-money validation of the whole stack moves one phase later.
- Two market-data sources for the same instruments will eventually run side by side; downstream consumers must dedupe duplicate ticks (already noted in ADR-005).

### Phase-number mapping for earlier documents

ADRs 001–006 predate this re-scope and are left unmodified. Where they reference phases, read them with this mapping:

| Reference in ADR-001…006 | Now means |
|---|---|
| "Phase 4 (execution)" / "Phase 4 (live execution)" / "Phase 4 introduces trading keys" | Phase 5 |
| "Phase 4+ (execution, backtesting)" (ADR-005) | backtesting: Phase 4 · execution: Phase 5 |
| "Phase 5" (regime detection, paid vendors, equities) | Phase 6 |

One ADR-005 note becomes immediately relevant rather than deferred: Kraken v2 ticker items carry no venue timestamp (`event_time == ingest_time`), which matters for backtest point-in-time correctness. The delivered Phase 4 implementation addresses it — see the Backtest replay section of `docs/architecture.md`. *(This originally pointed to a planned `docs/phase4-plan.md`; that plan was folded into `PLANNING.md` §9 Phase 4 and `docs/architecture.md` rather than landing as a separate file.)*

## Superseding renumber — 2026-06-10

A second roadmap re-scope (PLANNING v0.4) inserted a new Phase 5 (Watchlist & Multi-Instrument Scale) between the backtest phase and live trading. Phase numbers from this ADR now map as follows:

| Reference in this ADR | Current phase |
|---|---|
| "Phase 5" (live trading) | **Phase 6** |
| "Phase 6" (Scale & Autonomy) | **Phase 7** |
| "Phase 7" (Harden & Extend) | **Phase 8** |

All other content of this ADR remains accurate.

## When to revisit

- At Phase 6 kickoff: commit the live execution venue (Coinbase Advanced Trade vs Kraken) and revisit ADR-003 key permissioning for trade scope.
- If Coinbase public-feed auth requirements change again, re-evaluate the secondary-feed posture.
