# ADR-001: Event Bus Contract

**Status:** Accepted
**Date:** 2026-06-09
**Deciders:** @smithd36

---

## Context

AFTERHOURS is a modular monolith with eleven subsystems (see PLANNING §2). Those subsystems need to communicate in a way that:

1. **Decouples producers from consumers** - adding a new consumer (a new risk monitor, a new UI panel, a new logging sink) must not require touching producers.
2. **Enables the audit trail** - every meaningful event must be persisted and replayable, since "why did we buy X at 14:32?" must be answerable months later.
3. **Powers the live UI feeds** - the terminal's real-time panels are just subscriptions to bus topics, not separate polling loops.
4. **Supports backtesting** - the backtest engine replays historical events through the same reasoning/risk/execution path; the bus is the seam where mock adapters slot in.
5. **Stays operable as a monolith** - we are not running a distributed message broker in Phase 0. The contract must be clean enough to swap the transport without changing the contract.

---

## Decision

**All inter-subsystem communication is event-driven and flows through a single event bus.**

### The EventEnvelope

Every event on the bus is an `EventEnvelope` (see `core/schemas/events.py`). The envelope carries:

| Field | Purpose |
|---|---|
| `id` | Unique event identity (UUID). Used for dedup on replay. |
| `event_type` | Dotted string from `EventType` enum. Consumers deserialize `payload` based on this. |
| `source` | The subsystem that emitted the event. |
| `schema_version` | Schema version for forward-compatibility. Bump on breaking changes. |
| `event_time` | **When the domain event occurred** (market/source clock). Used for all financial logic and point-in-time features. |
| `ingest_time` | When we published it onto the bus (our clock). Used only for operational monitoring. |
| `correlation_id` | Threads all events in one Decision lifecycle together (see below). |
| `payload` | The typed body. Type is determined by `event_type`. |

### Two clocks - never confuse them

`event_time` vs `ingest_time` is the most common source of look-ahead bias in financial systems. Rule: **all financial logic uses `event_time`; operational monitoring uses `ingest_time`.**

### Topic naming

```
{domain}.{noun}.{verb}
```

- Domain: `market | signal | thesis | decision | order | portfolio | risk | system`
- Wildcard subscriptions are by prefix: `"decision.*"` catches all decision lifecycle events.
- The full registry is in `EventType` (Python) and `core.ts` (TypeScript). **No raw topic strings anywhere in application code** - always use the enum constants.

### Correlation ID

The `Decision.id` is the `correlation_id` for all events in that decision's lifecycle:

```
decision.proposed  ─┐
decision.approved  ─┤  all share correlation_id = Decision.id
order.submitted    ─┤
order.filled       ─┤
decision.executed  ─┘
```

This makes it trivial to reconstruct the full history of any trade.

### Transport (phased)

| Phase | Transport | Notes |
|---|---|---|
| 0–3 | **In-process pub/sub + Postgres event table** | One process; events appended to `events` table (source of audit truth); in-memory fan-out to subscribers. Zero external dependencies. |
| 4+ | **Redis Streams or NATS JetStream** | Extract to out-of-process when execution isolation or throughput demands it. Contract is identical - only the `Bus` implementation changes. |

The application code never knows which transport is in use. It calls `bus.publish(envelope)` and `bus.subscribe(pattern, handler)`. The `Bus` interface is the only coupling point.

### Immutability

Events are immutable once published. Corrections are new events (e.g., a reconciliation event that supersedes a prior position snapshot), never edits to existing events. The event table is append-only.

---

## The Decision Object as the central artifact

`Decision` (see `core/schemas/decision.py`) is the load-bearing domain object. Its lifecycle maps 1:1 onto `decision.*` events. Key properties:

- **Immutable once created** - status transitions are new events, not mutations of the Decision row.
- **Point-in-time `input_signal_ids`** - records exactly what the model saw; enables deterministic audit replay even after signal payloads are updated.
- **`prompt_hash` in `ModelInfo`** - sha256 of the fully rendered prompt; locks the reasoning to an exact call for calibration measurement.
- **Separation of duties enforced in the schema** - `Proposal.size_usd` is set by the sizing module, not the LLM. `RiskAssessment.risk_engine_verdict` is set by the risk engine. The LLM's contribution is scoped to `reasoning`, `evidence`, `confidence`, and the directional elements of `Proposal`.

---

## Consequences

### Positive
- Adding a new consumer (new panel, new risk check, new logger) requires zero changes to producers.
- The audit log falls out naturally - every event is persisted before fan-out.
- Backtesting is clean - replay the event stream through the same handlers with mock adapters at the `Bus` level.
- The UI is just a subscriber - the WebSocket/SSE endpoint subscribes to relevant topics and forwards envelopes to the browser.
- `correlation_id` makes per-trade forensics trivial.

### Negative / constraints
- All inter-subsystem data must cross the envelope boundary as serialisable JSON. Deeply nested objects or large binary blobs should be stored separately (object store) with a reference in the payload, not embedded in the event.
- Schema version discipline is mandatory. Breaking changes to `EventType` payload shapes require bumping `schema_version` and writing migration notes.
- In-process pub/sub gives no durability guarantee on its own - the Postgres append before fan-out is what provides it. Consumers that crash mid-delivery replay from the table. This replay logic must be implemented before Phase 4 (live execution).

---

## Alternatives considered

### Direct method calls between modules
Rejected. Creates hidden coupling; adding a new consumer requires touching producers; no natural audit trail; can't replay for backtesting.

### REST/RPC between modules
Rejected. Synchronous coupling; adds latency for no benefit in a monolith; breaks the backtest replay model.

### Full Kafka from day one
Rejected. Significant ops overhead (brokers, ZooKeeper/KRaft, consumer groups) before the product is proven. The in-process + Postgres approach gives the same guarantees at monolith ops cost. Extract when throughput actually demands it.
