# AFTERHOURS Documentation

The documentation index. Start here.

## Current stage (2026-06-29)

Phases **0–5 **, **6A ** (alt-data signal feeds, 2026-06-15), **6B.1 ** (disclosure-driven
discovery engine, 2026-06-16). **6B.2 pending** (breadth scanner / crypto-primary / auto-add).
**Phase 7 (live trading, staged 7A–7D) is not started** - the system is **paper-only**; no real
order has ever reached a venue.

## Reading order

A new contributor's path, shortest-to-deepest:

1. [`../README.md`](../README.md) - project front door: what it is, quick start, phase table.
2. [`../PLANNING.md`](../PLANNING.md) - the vision, the locked decisions, the phase roadmap, and the
   autonomy graduation gates (Appendix B). The "why."
3. [`architecture.md`](architecture.md) - canonical system design: subsystem map, event bus, the
   Decision object, data-flow traces. The "how it's built."
4. [`development.md`](development.md) - setup, commands, environment variables, API endpoints,
   running tests and backtests.
5. [`operator-guide.md`](operator-guide.md) - how the terminal behaves *today*: autonomy modes, the
   kill switch, the decision lifecycle, risk controls. The "how to drive it."
6. [`adr/`](adr/) - the Architecture Decision Records (see [`adr/README.md`](adr/README.md) for the
   index). The immutable decision log behind the choices above.

## Document map

| Document | Purpose |
|---|---|
| [`architecture.md`](architecture.md) | Canonical system design - subsystems, event bus, Decision object, data flow |
| [`development.md`](development.md) | Dev setup, commands, env vars, endpoints, tests, backtests |
| [`operator-guide.md`](operator-guide.md) | How to operate the terminal today (modes, HALT, risk controls) |
| [`phase-7-plan.md`](phase-7-plan.md) | The live-trading (Phase 7) staged plan - entry gates + exit checklists for 7A–7D |
| [`pre-phase-7-risk-review.md`](pre-phase-7-risk-review.md) | Pre-live money-loss review - the carry-over risks to action before the first live key |
| [`phase-6a-limitations.md`](phase-6a-limitations.md) | Known limitations of the Phase 6A alt-data feeds (deliberate scope, with upgrade paths) |
| [`adr/README.md`](adr/README.md) | Index of all Architecture Decision Records (001–012) |

## Diagrams

- [`pipeline.svg`](pipeline.svg) - the full event pipeline (ingestion → thesis → decision → risk →
  execution), with the event topic on every handoff.
- [`pipeline-simple.svg`](pipeline-simple.svg) - the same flow in plain language.

---

*When this index and the code disagree, the code wins - tell the maintainer and the docs get fixed.*
