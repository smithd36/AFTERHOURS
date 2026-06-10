"""
Event envelope and topic registry — the event-bus contract.

Every meaningful thing in AFTERHOURS is an immutable event published to the bus.
The audit log IS the event stream; the UI feeds ARE bus subscriptions.

Topic naming convention: {domain}.{noun}.{verb}
  - domain:  market | signal | thesis | decision | order | portfolio | risk | system
  - noun:    the entity (tick, fill, position, feed, mode, ...)
  - verb:    past tense (created, updated, approved, breached, ...)

Wildcard subscriptions: "decision.*" catches all decision lifecycle events.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Event envelope
# ---------------------------------------------------------------------------


class EventEnvelope(BaseModel):
    """
    Wraps every event on the bus. Consumers deserialize `payload` based
    on `event_type` (see EventType below for the full registry).

    `correlation_id` threads related events together:
      decision.proposed → decision.approved → order.submitted → order.filled
      all share the same correlation_id (the Decision.id).
    """

    id: UUID = Field(default_factory=uuid4)
    event_type: str  # dotted string from EventType enum
    source: str  # subsystem that emitted it, e.g. "reasoning_engine", "execution_engine"
    schema_version: str = "1.0"

    # Two clocks (see PLANNING §4.6 and Provenance in common.py)
    event_time: datetime  # when the domain event occurred (UTC)
    ingest_time: datetime  # when we published it onto the bus (UTC)

    correlation_id: Optional[UUID] = None  # links all events for one Decision lifecycle
    payload: dict[str, Any]  # typed body; deserialize using event_type as key


# ---------------------------------------------------------------------------
# Topic registry
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    """
    Exhaustive registry of all bus topics.
    Keep this file as the single source of truth — both producers and
    consumers must use these constants, never raw strings.
    """

    # --- Market data ---
    # High-frequency; consumers should subscribe selectively by instrument.
    MARKET_TICK = "market.tick"  # payload: {instrument, price, volume, ts}
    MARKET_ORDERBOOK = "market.orderbook"  # payload: {instrument, bids, asks, ts}
    MARKET_OHLCV = "market.ohlcv"  # payload: {instrument, open, high, low, close, volume, interval}

    # --- Signals ---
    SIGNAL_CREATED = "signal.created"  # payload: Signal
    SIGNAL_UPDATED = "signal.updated"  # payload: {signal_id, changes}

    # --- Theses ---
    THESIS_CREATED = "thesis.created"  # payload: Thesis
    THESIS_UPDATED = "thesis.updated"  # payload: {thesis_id, changes}
    THESIS_INVALIDATED = "thesis.invalidated"  # payload: {thesis_id, reason, signal_id}

    # --- Decision lifecycle (all share correlation_id = Decision.id) ---
    DECISION_PROPOSED = "decision.proposed"  # payload: Decision (status=PROPOSED)
    DECISION_APPROVED = "decision.approved"  # payload: {decision_id, human?, risk_verdict}
    DECISION_REJECTED = "decision.rejected"  # payload: {decision_id, reason, actor}
    DECISION_EXPIRED = "decision.expired"  # payload: {decision_id}
    DECISION_EXECUTING = "decision.executing"  # payload: {decision_id}
    DECISION_EXECUTED = "decision.executed"  # payload: {decision_id, outcome}
    DECISION_FAILED = "decision.failed"  # payload: {decision_id, error}
    DECISION_RESOLVED = "decision.resolved"  # payload: {decision_id, predicted_side, confidence,
    #   mode_at_proposal, entry_price, resolution_price, realized_return_pct (side-adjusted),
    #   hit, resolution_reason, proposed_at, resolved_at} — emitted by the outcome resolver
    #   when a decision's prediction is scored against realized price action (calibration input)

    # --- Orders ---
    ORDER_SUBMITTED = "order.submitted"  # payload: {order_id, decision_id, ...}
    ORDER_FILLED = "order.filled"  # payload: Fill
    ORDER_PARTIALLY_FILLED = "order.partially_filled"  # payload: Fill
    ORDER_CANCELLED = "order.cancelled"  # payload: {order_id, reason}
    ORDER_FAILED = "order.failed"  # payload: {order_id, error}

    # --- Portfolio ---
    PORTFOLIO_POSITION_UPDATED = "portfolio.position_updated"  # payload: Position snapshot
    PORTFOLIO_RECONCILED = "portfolio.reconciled"  # payload: {ts, divergences}
    PORTFOLIO_RECONCILIATION_FAILED = "portfolio.reconciliation_failed"  # triggers halt review

    # --- Risk ---
    RISK_LIMIT_APPROACHED = "risk.limit_approached"  # payload: {limit_type, current, threshold}
    RISK_LIMIT_BREACHED = "risk.limit_breached"  # payload: {limit_type, current, limit}
    RISK_HALT = "risk.halt"  # payload: {reason, scope, actor}; kill switch fired

    # --- Watchlist ---
    WATCHLIST_INSTRUMENT_ADDED = "watchlist.instrument_added"  # payload: {instrument, market}
    WATCHLIST_INSTRUMENT_REMOVED = "watchlist.instrument_removed"  # payload: {instrument, market}

    # --- System / observability ---
    SYSTEM_FEED_HEALTHY = "system.feed_healthy"  # payload: {feed_id, ts}
    SYSTEM_FEED_DEGRADED = "system.feed_degraded"  # payload: {feed_id, latency_ms, ts}
    SYSTEM_FEED_DEAD = "system.feed_dead"  # payload: {feed_id, last_seen_ts}
    SYSTEM_MODE_CHANGED = "system.mode_changed"  # payload: {from_mode, to_mode, actor, reason}
    SYSTEM_ERROR = "system.error"  # payload: {subsystem, error, severity}


# ---------------------------------------------------------------------------
# Autonomy mode (referenced in SYSTEM_MODE_CHANGED events)
# ---------------------------------------------------------------------------


class AutonomyMode(str, Enum):
    """
    The graduated autonomy ladder (PLANNING §5).
    Mode changes are audited events; demotion triggers are enforced by the
    risk engine and autonomy monitor (PLANNING Appendix B).
    """

    OBSERVE = "observe"  # read-only; shadow decisions logged for calibration only
    PAPER = "paper"  # full pipeline, simulated fills
    ASSISTED = "assisted"  # every order requires explicit operator approval
    SEMI_AUTO = "semi_auto"  # executes within a pre-approved bounded envelope
    SUPERVISED = "supervised"  # broader limits; operator monitors and can halt
