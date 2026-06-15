"""
Signal: a normalized observation from any source.
Thesis: a persistent, instrument-scoped belief with invalidation conditions.

Signals are the raw inputs the reasoning engine consumes.
Theses are longer-lived hypotheses that persist across many decisions;
they give the system coherence over time rather than tick-by-tick reactivity.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .common import Provenance


class SignalType(str, Enum):
    PRICE_ALERT = "price_alert"
    NEWS = "news"
    INDICATOR_CROSSING = "indicator_crossing"
    ON_CHAIN = "on_chain"
    ECONOMIC_EVENT = "economic_event"
    SENTIMENT = "sentiment"
    INSIDER_TX = "insider_tx"  # SEC Form 4 insider transaction (Phase 6A alt-data)
    CONGRESSIONAL_TX = "congressional_tx"  # STOCK Act disclosure (Phase 6A alt-data)
    LOBBYING = "lobbying"  # Senate LDA lobbying disclosure (Phase 6A alt-data)
    GOV_CONTRACT = "gov_contract"  # USASpending federal contract award (Phase 6A alt-data)
    SUPPLY_CHAIN = "supply_chain"  # 10-K customer-concentration dependency (Phase 6A alt-data)
    CUSTOM = "custom"


class Signal(BaseModel):
    """
    A normalized, provenance-tagged observation.
    All ingested text in `payload` is untrusted data — never treated as
    instructions (prompt-injection guard; see PLANNING §6.2).
    """

    id: UUID = Field(default_factory=uuid4)
    type: SignalType
    instruments: list[str]  # canonical symbols this signal relates to
    provenance: Provenance
    payload: dict[str, Any]  # type-specific content; schema varies by SignalType
    relevance_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    embedding_id: Optional[str] = None  # reference into the vector store for retrieval


class ThesisStatus(str, Enum):
    ACTIVE = "active"
    INVALIDATED = "invalidated"  # an invalidation condition was met
    EXPIRED = "expired"  # time horizon elapsed without resolution
    CLOSED = "closed"  # operator manually closed


class Thesis(BaseModel):
    """
    A persistent, instrument-scoped belief the system holds.
    e.g. "BTC re-rating on ETF inflows; valid while inflows > X and price > Y."
    Theses are revisited continuously; invalidation_conditions are checked
    automatically against incoming signals.
    """

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime
    updated_at: datetime
    instrument: str  # canonical symbol
    summary: str  # one-liner: "BTC re-rating on ETF inflows"
    body: str  # full narrative with evidence
    status: ThesisStatus = ThesisStatus.ACTIVE
    invalidation_conditions: list[str]  # plain-language conditions that kill this thesis
    supporting_signal_ids: list[UUID] = Field(default_factory=list)
    decision_ids: list[UUID] = Field(default_factory=list)  # Decisions spawned from this thesis
