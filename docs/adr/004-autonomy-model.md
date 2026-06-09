# ADR-004: Graduated Autonomy Model

**Status:** Accepted — binding, non-negotiable
**Date:** 2026-06-09
**Deciders:** Lead Architect

---

## Context

AFTERHOURS will eventually execute trades with real capital, partly or fully initiated by an AI model. Unconstrained AI autonomy over a trading account is unacceptable — a miscalibrated model, a prompt injection, a regime break, or a software bug could cause large losses before a human has time to intervene.

The autonomy model must:
1. Start with zero AI agency over real capital.
2. Require demonstrated calibration before any promotion.
3. Demote automatically when calibration or operational signals deteriorate.
4. Always allow a human to halt the system instantly.

---

## Decision

### Five autonomy modes

| Mode | Human role | AI role | Capital at risk |
|---|---|---|---|
| **Observe** | Monitors only | Generates theses and proposals — no action taken | None |
| **Paper** | Monitors only | Full decision cycle, but orders go to paper account | Simulated only |
| **Assisted** | Approves each trade | AI proposes; human approves or rejects before any order | Real, gated |
| **Semi-auto** | Sets limits, monitors | AI executes within pre-approved size/risk limits | Real, bounded |
| **Supervised** | Monitors, can halt | AI executes freely within risk engine limits | Real, full |

The system starts in **Observe** mode. No path to live capital without passing through Paper and Assisted first.

### Primary promotion gate: ECE

The primary metric for mode promotion is **ECE (Expected Calibration Error)**, not P&L.

A well-calibrated model that says "60% confident" is right approximately 60% of the time. This is measurable without market exposure (paper trading provides the sample). P&L is too noisy and too slow for early-phase evaluation — a model can be profitable by luck and still be dangerously miscalibrated.

ECE threshold for promotion from Paper to Assisted: `ECE < 0.10` over a minimum of 50 decisions.

Secondary metrics (used alongside ECE, not as replacement):
- Accuracy on directional calls (> chance)
- Max drawdown in paper simulation
- Evidence quality (are cited Signals real, non-stale, and relevant?)

### Demotion triggers (automatic)

Any of the following triggers an immediate demotion to the previous safe mode:

| Trigger | Description |
|---|---|
| **Calibration drift** | Rolling ECE exceeds threshold over last N decisions |
| **Drawdown breach** | Unrealised or realised loss exceeds configured limit |
| **Recon error** | Position reconciliation fails or finds unexpected discrepancy |
| **Model version change** | New model ID or breaking prompt change — recalibrate from scratch |
| **Regime break** | Detected market regime change (Phase 5 — volatility, correlation) |
| **Prompt injection detected** | Untrusted content (news, social) appears in reasoning path |

On demotion, a `system.mode_changed` event is published with `from_mode`, `to_mode`, and `trigger` fields. All demotion events are persisted.

### Kill switch

A kill switch is available at all times, regardless of mode. Activating it:
1. Sets mode to **Observe** (zero autonomy)
2. Cancels all open orders
3. Publishes `risk.halt` event
4. Requires manual re-activation

The kill switch is implemented in the risk engine (Phase 3) and is the first feature built in that phase.

### The `AutonomyMode` enum

```python
class AutonomyMode(str, Enum):
    OBSERVE    = "observe"
    PAPER      = "paper"
    ASSISTED   = "assisted"
    SEMI_AUTO  = "semi_auto"
    SUPERVISED = "supervised"
```

Mode state is carried in `system.mode_changed` events and stored durably. All decision-making code reads the current mode before producing a `Decision` — the mode determines whether the proposal is executed, queued for approval, simulated, or dropped.

---

## Consequences

### Positive
- Zero path from "AI generates idea" to "real order placed" without demonstrated calibration.
- Automatic demotion means the system responds to its own failures without requiring a human to notice in real time.
- ECE as gate metric decouples "is the model calibrated?" from "is the market moving in our favour?" — the latter is outside our control, the former is not.
- The kill switch is a hard constraint at the infrastructure level — it is not a UI button that can be ignored by application code.

### Negative / constraints
- ECE measurement requires a sufficient sample (50+ decisions) before any promotion. This means Paper mode lasts weeks or months in practice.
- Calibration in Paper mode may not generalise perfectly to live trading (market impact, slippage, execution latency differ). Paper performance is a necessary but not sufficient condition for live performance.
- Regime change detection (demotion trigger) is complex to implement correctly and is deferred to Phase 5. Until then, the operator must manually demote if they observe a regime break.

---

## Relationship to the Decision Object

The `Decision` schema enforces the separation of duties required by this autonomy model:

- `Proposal.size_usd` — set by the **sizing module**, not the LLM. The LLM cannot propose its own size.
- `RiskAssessment.risk_engine_verdict` — set by the **risk engine**. A `rejected` verdict blocks execution regardless of confidence.
- `Decision.status` — transitions follow the autonomy mode. In `Observe`, proposals never reach `executing`.

The model is not trusted to self-report its confidence accurately — hence ECE measurement as an external calibration check.
