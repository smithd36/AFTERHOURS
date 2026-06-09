"""
Decision: the central artifact. Immutable once created.

Every dollar of real risk traces back to a Decision. The full lifecycle —
proposed by the AI, assessed by the risk engine, actioned by the operator,
executed by the execution engine, resolved by outcome — is captured here.

Key invariant: the LLM contributes reasoning, evidence, confidence, and
direction (instrument/side/time_horizon). The sizing code computes size_usd
deterministically. The risk engine then either approves, rejects, or scales
it. The LLM never directly sets size_usd (PLANNING §4.5).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DecisionStatus(str, Enum):
    PROPOSED = "proposed"  # emitted by the reasoning engine, awaiting risk check
    APPROVED = "approved"  # cleared risk engine + operator action (Assisted mode)
    REJECTED = "rejected"  # rejected by risk engine or operator
    EXPIRED = "expired"  # time_horizon elapsed before action
    EXECUTING = "executing"  # handed to execution engine
    EXECUTED = "executed"  # all fills received
    FAILED = "failed"  # execution error after approval


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LIMIT = "stop_limit"


class TimeHorizon(str, Enum):
    SCALP = "scalp"  # minutes
    INTRADAY = "intraday"  # hours
    SWING = "swing"  # days–weeks
    POSITION = "position"  # weeks–months


class HumanActionType(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"  # approved with size/price changes
    SNOOZED = "snoozed"
    CONVERTED_TO_ALERT = "converted_to_alert"


class RiskVerdict(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"  # approved but size scaled down by the risk engine


# ---------------------------------------------------------------------------
# Nested value objects
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    """
    A single piece of supporting or contradicting evidence.
    Every evidence item must cite a real ingested Signal — the reasoning
    engine must not fabricate evidence (PLANNING §6.2, additional feature #1).
    """

    signal_id: UUID
    summary: str  # one-line human-readable description
    stance: Literal["supporting", "contradicting"]


class ModelInfo(BaseModel):
    """Exact provenance of the model call that produced this Decision."""

    provider: str  # "anthropic"
    model_id: str  # "claude-sonnet-4-6"
    prompt_hash: str  # sha256 of the fully rendered prompt (for audit + calibration)
    temperature: float


class Proposal(BaseModel):
    """
    What the system proposes to do.
    `size_usd` is computed by the sizing module, not the LLM.
    `limit_price` is required when order_type is LIMIT or STOP_LIMIT.
    """

    instrument: str  # canonical symbol, e.g. "BTC-USD"
    side: Side
    size_usd: Decimal  # deterministic sizing output; never LLM-generated
    order_type: OrderType
    limit_price: Optional[Decimal] = None
    time_horizon: TimeHorizon


class RiskAssessment(BaseModel):
    """
    Output of the deterministic risk engine.
    This is authoritative: the execution engine will not proceed without
    verdict == APPROVED or MODIFIED (PLANNING §2.4, §4.5).
    """

    max_loss_pct: float  # maximum acceptable loss as % of portfolio
    stop_price: Optional[Decimal] = None
    invalidation_conditions: list[str]  # conditions that should trigger exit
    risk_engine_verdict: RiskVerdict
    rejection_reasons: list[str] = Field(default_factory=list)
    effective_size_multiplier: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="1.0 = unchanged; <1.0 = risk engine scaled down size_usd",
    )


class HumanAction(BaseModel):
    """Operator interaction record. Absent means no human has acted yet."""

    actor: str  # operator identifier
    action: HumanActionType
    note: Optional[str] = None  # required for REJECTED (captures training signal)
    ts: datetime
    edits: Optional[dict[str, Any]] = None  # field-level diff for EDITED actions


class Fill(BaseModel):
    """A single execution fill. Decisions may have multiple partial fills."""

    fill_id: str  # exchange-issued
    order_id: str  # our idempotency key
    ts: datetime
    price: Decimal
    quantity: Decimal
    fee: Decimal
    fee_currency: str


class DecisionOutcome(BaseModel):
    """Filled in progressively as execution happens and the trade closes."""

    order_ids: list[str] = Field(default_factory=list)
    fills: list[Fill] = Field(default_factory=list)
    realized_pnl: Optional[Decimal] = None
    closed_at: Optional[datetime] = None
    slippage_pct: Optional[float] = None  # (avg_fill - proposal_price) / proposal_price


# ---------------------------------------------------------------------------
# The Decision Object
# ---------------------------------------------------------------------------


class Decision(BaseModel):
    """
    The central artifact. Immutable once status moves past PROPOSED.

    Lifecycle:
      PROPOSED → (risk engine) → APPROVED/REJECTED
      APPROVED → (operator, in Assisted mode) → APPROVED/REJECTED/EDITED
      APPROVED → EXECUTING → EXECUTED / FAILED
      PROPOSED/APPROVED → EXPIRED (time_horizon elapsed)

    The `input_signal_ids` list is point-in-time: it records exactly the
    signals the model saw when it generated this decision, enabling exact
    audit replay even after signal payloads are updated.
    """

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime
    originating_thesis_id: Optional[UUID] = None

    # --- what the model saw (point-in-time, for audit replay) ---
    input_signal_ids: list[UUID]

    # --- AI contribution ---
    model: ModelInfo
    proposal: Proposal  # instrument + side + time_horizon (LLM); size_usd (sizing code)
    reasoning: str  # narrative from the LLM
    evidence: list[Evidence]  # must be non-empty; every item cites a real Signal
    confidence: float = Field(ge=0.0, le=1.0)

    # --- risk engine assessment (authoritative, filled in by risk engine) ---
    risk: Optional[RiskAssessment] = None

    # --- lifecycle ---
    status: DecisionStatus = DecisionStatus.PROPOSED
    human: Optional[HumanAction] = None
    outcome: Optional[DecisionOutcome] = None
