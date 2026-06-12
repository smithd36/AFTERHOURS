# ADR-008: Single Source of Truth for Autonomy Mode

**Status:** Accepted
**Date:** 2026-06-12
**Deciders:** Lead Architect

---

## Context

The autonomy mode (ADR-004) governs whether a proposal is executed, queued for approval, simulated, or dropped. It is the most safety-critical piece of mutable state in the system.

Originally the mode lived in **four independent places** — `app.state.autonomy_mode` (gateway), `RiskEngine._mode`, `PaperExecutor._mode`, and `OutcomeResolver._mode` — each kept in sync by separately handling `system.mode_changed`. This is the event bus working as designed for *derived* state (ADR-001), but mode is not derived state: it is a single authoritative value that gates real money.

Two failure modes followed:

1. **Sync divergence.** A `system.mode_changed` event that is dropped, reordered, or delivered to handlers in a different order leaves two subsystems believing they are in different modes. In paper this is a logging curiosity; once the live executor lands in Phase 6 (ADR-007), a trade could be placed under the wrong mode.
2. **Write-after-publish race.** The mode route published `system.mode_changed` and *then* mutated `app.state.autonomy_mode`, so during fan-out a consumer reading app state could disagree with the event it had just received.

Per PLANNING §5, the mode must have exactly one owner, and a restart must fail safe to OBSERVE.

---

## Decision

**A single `ModeController` (`core/mode.py`) owns the autonomy mode. Every component reads it; no component caches its own copy.**

- The value changes in exactly one place — `ModeController.set()` (a validated operator transition) and `ModeController.halt()` (the kill switch). Both update the in-memory value **before** publishing the audit event, so any subscriber that reads `current` during fan-out already sees the new mode. The write-after-publish race is structurally impossible.
- `system.mode_changed` and `risk.halt` remain the durable audit trail and still drive *reactive side effects* (e.g. the executor flushing parked decisions on demotion). They are no longer the mechanism by which any component learns the current mode — that is always a live read of `ModeController.current`.
- Transition validation (the legal-move table) and the kill switch live on the controller, not scattered across routes. The mode route and halt route are thin: they call `set()` / `halt()` and translate an `InvalidModeTransition` into HTTP 422.
- One `ModeController` is constructed in the gateway lifespan and injected into the risk engine, paper executor, and outcome resolver. The backtest runner constructs its own (fixed for the run).
- **Restart fail-safe:** the mode is deliberately *not* persisted. Every process starts in OBSERVE and stays read-only until the operator explicitly promotes it, so a crash or redeploy can never silently resume live trading.

### Why not keep it event-synced?

Event sync is correct for state that is a *projection* of the event stream (calibration metrics, the decision store). Mode is not a projection — it is the input that decides whether capital moves. For that, a missed event must be impossible to act on, which means there can be only one copy and it must be read, never replicated.

---

## Consequences

### Positive
- No subsystem can trade under a stale mode: authority is a live read of one object. A dropped or reordered `system.mode_changed` can no longer cause silent disagreement.
- The kill switch is atomic — `halt()` forces OBSERVE before emitting `risk.halt`, so a decision being re-validated inside a halt handler is already gated to OBSERVE.
- Transition rules and validation have one home; routes carry no mode logic.
- The audit trail is unchanged — the same events are still published and persisted.

### Negative / constraints
- The controller must be injected wherever mode is read; a component constructed without it (unit tests) falls back to a private controller seeded at `initial_mode`. Production and backtest paths must pass the shared instance explicitly.
- Mode is process-local and intentionally non-persistent. Restoring a non-OBSERVE mode after a restart is a deliberate operator action, never automatic.

---

## Alternatives considered

**Persist mode and rehydrate on startup.** Rejected: a process that resumes live trading on its own after a crash is exactly the fail-open behaviour the autonomy model forbids (ADR-004). OBSERVE-on-restart is the safe default.

**Keep event sync but add sequence numbers / acks.** Rejected: this rebuilds a reliable-delivery layer to protect a value that does not need to be distributed at all inside a monolith. One owner is simpler and removes the failure class entirely.

**Make every consumer query the gateway route for the mode.** Rejected: adds latency and a synchronous coupling to the gateway on a hot path (every proposal), and reintroduces a copy (the route's app-state value) as the thing being read.

---

## Relationship to other ADRs

- **ADR-001 (event bus):** mode-change and halt events still flow through the bus as the audit trail; this ADR narrows their role to audit + reactive side effects, not state replication.
- **ADR-004 (autonomy model):** this is the implementation of "all decision-making code reads the current mode" and the kill switch, with the restart fail-safe made explicit.
