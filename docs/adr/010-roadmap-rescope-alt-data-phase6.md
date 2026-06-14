# ADR-010: Roadmap Re-scope — Alternative-Data Ingestion Inserted as Phase 6; Live Trading Shifts to Phase 7

**Status:** Accepted
**Date:** 2026-06-13
**Deciders:** Operator, Lead Architect

---

## Context

Phase 5 (watchlist + multi-instrument scale) is complete and the pre-live-trading hardening
blockers are closed (2026-06-12). The standing roadmap put **live trading (Phase 6, staged
6A–6D)** as the next code pass.

Before committing real capital, we want to widen the signal surface for the equity book with
**alternative data**: Congressional / STOCK Act disclosures, insider transactions (Form 4),
dark-pool / options flow, corporate lobbying, government contracts, and supply-chain /
quiet-partner relationships. Two reasons to do this *before* live trading rather than after:

1. **It is paper-only and zero real-money risk** — it exercises the existing ingestion →
   signal → thesis → decision → calibration path with no broker keys, so it can land while the
   live-execution entry gate (gateway auth/bind hardening) is still being closed.
2. **More signal earns calibration evidence faster.** The Appendix B gates that authorise live
   trading are measured on resolved decisions; a richer, equity-relevant signal set produces more
   (and more diverse) decisions to calibrate against, strengthening the evidence base for the
   *now-later* live phase.

Live trading is "a few weeks out at best" regardless, so deferring it one phase costs nothing on
the critical path.

The integration design (full ingestion→execution trace, the three gates alt-data must clear —
watchlist, thesis-trigger, price-for-stop — and the enrich-only vs. auto-discovery split) was
worked out in planning and is summarised in the Decision below.

## Decision

1. **A new Phase 6 — Alternative Data Source Integration** is inserted after Phase 5, in two
   sub-phases:
   - **Phase 6A — Alt-data signal feeds (enrich-only).** One pluggable poller per source, each
     emitting `signal.created` through the *same bus contract* as `NewsFeed`/`PriceAlertGenerator`
     — no new feed framework; the `signal.created` contract is the plug. New `SignalType` members
     (mirrored in `frontend/src/types/core.ts`). Each normalizer applies a **materiality filter**
     and writes a human-readable `summary` (the thesis prompt only renders `summary`/`title`) plus
     a `factor` tag for correlation grouping. **Two-clock rule is load-bearing:** `event_time` is
     the public **disclosure/availability** date, never the transaction date — using the
     transaction date is look-ahead bias and would act on not-yet-public information. A
     **thesis-seed trigger** is added to `ThesisGenerator` so a single material alt-data signal can
     seed a thesis (the existing minutes-wide accumulation window never fires for sparse signals).
     **Enrich-only:** alt-data trades only watchlist instruments that are already price-fed (the
     risk engine requires a live price to compute a stop); unwatched-ticker disclosures are still
     ingested, persisted, and surfaced in the terminal for one-click watchlist-add, but do not
     auto-trade. First feed is **Form 4 / SEC EDGAR** (free, ≤2-day, best backtestability).
   - **Phase 6B — Auto-discovery.** Promote a high-conviction alt-data signal on an *unwatched*
     instrument to **auto-add** it to the watchlist (→ `FeedRouter` → `EquityFeed` price →
     tradable), behind guardrails: a discovery cap, operator confirm and/or auto-expiry, and
     **liquidity-aware sizing** for the illiquid small-caps these signals surface. Deliberately
     split out of 6A — discovery is a control-plane problem, not an ingestion one — and kept out of
     the next code pass, but on record here so it is not lost.

2. **Live trading becomes Phase 7**, keeping its four sub-phases, renumbered **7A–7D** (was
   6A–6D). All later phases shift down one: **Scale & Autonomy → Phase 8**, **Harden & Extend →
   Phase 9**.

3. **No real money in Phase 6.** Alt-data runs in the existing Observe / Paper / Assisted-paper
   modes. The "no real money until <live phase>" rule now reads **until Phase 7**.

4. **Compliance posture for the new sources** (PLANNING §6.5): Form 4, Congressional disclosures,
   lobbying, and government contracts are **public record** — legal to use, no MNPI concern.
   **Supply-chain / quiet-partner data is restricted to public-filing-derived relationships
   (10-K Item 1).** Sourcing supply-chain intel from expert networks or channel checks is an
   explicit **MNPI stop** and is out of scope. Paid feeds (options flow / dark pool) are deferred
   within 6A and gated on the cheap public sources proving out first.

## Consequences

### Positive
- Live trading is de-risked by a larger calibration sample before the first real dollar, matching
  the "autonomy is earned" doctrine (PLANNING §5, §11).
- Phase 6 needs **no exchange/execution keys** — at most free-tier *data* keys (SEC EDGAR needs
  none; Quiver/Alpaca-data free tiers). The no-execution-secrets posture of Phases 0–5 extends
  through Phase 6.
- Each alt-data feed is off the critical path and degrades gracefully (swallow-and-log,
  `system.feed_degraded`); a dead alt-data feed never affects price feeds or open positions.
- Auto-discovery is captured as a planned, gated phase rather than smuggled into the first pass.

### Negative / constraints
- Real-money validation of the stack moves one phase later (acceptable — live was weeks out).
- Alt-data alpha is days-to-weeks and, for Congressional data, 30–45 days stale on arrival; these
  signals must drive `swing`/`position` horizons, not `intraday`.
- Alt-data steers toward illiquid small-caps; the risk engine is currently liquidity-blind, so
  liquidity-aware sizing is a prerequisite for 6B (and a caveat even in 6A enrich-only).

## Phase-number mapping for earlier documents

ADRs 001–009 and the docs under `docs/` predate this re-scope and are **left unmodified** (the
established convention — see ADR-007). The detailed live-trading plan keeps its filename
`docs/phase-6-plan.md` to avoid breaking references; read it as the **Phase 7** plan. Where any
document references these phases, read them with this mapping:

| Reference in pre-2026-06-13 docs | Now means |
|---|---|
| "Phase 6" / "Phase 6 (live trading)" | **Phase 7** |
| "Phase 6A / 6B / 6C / 6D" (live-trading sub-phases) | **Phase 7A / 7B / 7C / 7D** |
| `docs/phase-6-plan.md`, `docs/pre-phase-6-issues.md`, `phase-6-blocker` labels | live-trading (now Phase 7) artifacts; filenames/labels retained |
| "Phase 7" (Scale & Autonomy) | **Phase 8** |
| "Phase 8" (Harden & Extend) | **Phase 9** |
| "no real money until Phase 6" | until **Phase 7** |

The new **Phase 6** in any current document means **alternative-data ingestion** (this ADR).

## When to revisit

- At Phase 6B kickoff: confirm the auto-discovery guardrails (discovery cap, confirm/expiry
  policy) and land liquidity-aware sizing in the risk engine first.
- If a paid alt-data feed (options flow / dark pool) is brought into 6A, re-confirm its ToS and
  redistribution terms (PLANNING §6.5) and its point-in-time backtestability before relying on it.
- Before Phase 7 (live trading) starts, this re-scope has no further bearing — the live plan
  (`docs/phase-6-plan.md`, ADR-009) stands as written, read one phase number higher.
