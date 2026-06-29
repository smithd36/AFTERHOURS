# Architecture Decision Records

ADRs capture the *why* behind significant architectural and product decisions. They are an
**immutable decision log**: an ADR records what was decided and the context at that time. When a
decision changes, we add a **new** ADR that supersedes the old one rather than editing history -
so superseded ADRs are kept as written, and this index is where current status is resolved.

> Some ADR bodies reference companion files by their original names (e.g. `docs/phase-6-plan.md`,
> `docs/pre-phase-6-issues.md`). Those are historical references left intact by design. The current
> equivalents are: the Phase 7 plan → [`../phase-7-plan.md`](../phase-7-plan.md); the pre-live
> hardening tracker → completed, with the standing pre-live reference now
> [`../pre-phase-7-risk-review.md`](../pre-phase-7-risk-review.md).

## Index

| # | Title | Status |
|---|---|---|
| [001](001-event-bus-contract.md) | Event Bus Contract | Accepted |
| [002](002-sqlite-local-storage.md) | SQLite for Local Event Storage | Accepted |
| [003](003-api-key-security.md) | API Key Security Policy | Accepted - binding, non-negotiable |
| [004](004-autonomy-model.md) | Graduated Autonomy Model | Accepted - binding, non-negotiable |
| [005](005-exchange-feed-architecture.md) | Exchange Feed Architecture - Kraken Primary, Coinbase Deferred | Accepted |
| [006](006-llm-thesis-layer.md) | LLM Thesis Layer - Pluggable Providers and Prompt-Level JSON | Accepted |
| [007](007-roadmap-rescope-phase4.md) | Roadmap Re-scope - Backtest & Calibration Before Live Trading; Kraken Confirmed Primary | Accepted - its *execution-venue* candidate (Coinbase) is superseded by ADR-009 |
| [008](008-mode-controller.md) | Single Source of Truth for Autonomy Mode | Accepted |
| [009](009-live-execution-venue.md) | Live Execution Venue - Alpaca (primary) + Kraken (secondary) | Accepted - supersedes the execution-venue note in ADR-007 |
| [010](010-roadmap-rescope-alt-data-phase6.md) | Roadmap Re-scope - Alt-Data Inserted as Phase 6; Live Trading Shifts to Phase 7 | Accepted - its Phase 6B definition is superseded by ADR-012 |
| [011](011-analytics-module.md) | A Dedicated Analytics Module for Risk/Return Measurement | Accepted |
| [012](012-discovery-engine-phase6b.md) | Discovery Engine - Phase 6B (Multi-Source Opportunity Surfacing) | Accepted - 6B.1 implemented 2026-06-16; 6B.2 pending |

## Supersession chain

- **ADR-009 → ADR-007:** the live *execution* venue is Alpaca primary + Kraken secondary, replacing
  ADR-007's "Coinbase Advanced Trade is the standing candidate." Market-*data* sourcing is unchanged
  (Kraken primary, Coinbase secondary).
- **ADR-012 → ADR-010:** the Phase 6B "auto-discovery" placeholder in ADR-010 is expanded into the
  multi-source discovery engine specified by ADR-012.
- **ADR-010** also renumbered the roadmap: alternative-data ingestion became Phase 6, and live
  trading shifted from Phase 6 to **Phase 7** (sub-phases 7A–7D).

See [`../README.md`](../README.md) for the documentation index and current project stage.
