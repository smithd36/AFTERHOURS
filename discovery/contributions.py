"""
A `Contribution` is one source's normalized, signed vote for an instrument.

Extractors map a persisted `signal.created` event into zero or more
Contributions; the scoring core (`score.py`) folds them into an opportunity
score. The extractor owns its source's units — the scorer only ever sees a
bounded, factor-tagged value in [-1, 1] (+ bullish, - bearish/risk context).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Contribution:
    instrument: str  # canonical symbol the evidence is about
    factor: str  # correlation family (e.g. "insider_activity") — see ADR-010
    value: float  # signed magnitude in [-1, 1]; + bullish, - bearish/risk
    event_time: datetime  # disclosure/availability clock — drives time-decay
    summary: str  # human-readable; the explanation substrate (ADR-012)
    source: str  # SignalType that produced it
    signal_id: str
