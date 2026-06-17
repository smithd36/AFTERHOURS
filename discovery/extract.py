"""
Turn a persisted ``signal.created`` event into discovery Contributions.

Pure mapping, no state. The envelope payload is a dumped ``Signal`` (see
``ingestion/*/normalizer.py``): ``{type, instruments, relevance_score,
payload: {summary, factor, direction, ...}}``. Only signals that 6A tagged with
a ``factor`` + ``summary`` are discovery-eligible; raw price alerts without a
factor are skipped.
"""

from __future__ import annotations

from typing import Any

from core.schemas.events import EventEnvelope, EventType

from .contributions import Contribution
from .resolve import resolve_instruments

# A disclosure's direction sets the sign: buys are bullish, sells bearish.
# "neutral" (e.g. supply-chain dependency) is risk *context*, not a directional
# vote — keep it positive but damped so it nudges rather than drives.
_SIGN: dict[str, float] = {"buy": 1.0, "sell": -1.0, "neutral": 1.0}
_NEUTRAL_DAMP = 0.5
_DEFAULT_RELEVANCE = 0.5


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def contributions_from_signal(env: EventEnvelope) -> list[Contribution]:
    if env.event_type != EventType.SIGNAL_CREATED:
        return []

    signal = env.payload
    if not isinstance(signal, dict):
        return []
    inner: dict[str, Any] = signal.get("payload") or {}

    factor = inner.get("factor")
    summary = inner.get("summary")
    if not factor or not summary:
        return []  # not a discovery-eligible signal (no correlation family)

    instruments = resolve_instruments(signal.get("instruments") or [])
    if not instruments:
        return []  # unresolved → drop, never guess (ADR-012)

    relevance = signal.get("relevance_score")
    magnitude = float(relevance) if relevance is not None else _DEFAULT_RELEVANCE

    direction = str(inner.get("direction", "neutral"))
    sign = _SIGN.get(direction, 1.0)
    if direction == "neutral":
        magnitude *= _NEUTRAL_DAMP

    value = _clamp(sign * magnitude, -1.0, 1.0)
    source = str(signal.get("type", ""))
    signal_id = str(signal.get("id", ""))

    return [
        Contribution(
            instrument=instrument,
            factor=str(factor),
            value=value,
            event_time=env.event_time,
            summary=str(summary),
            source=source,
            signal_id=signal_id,
        )
        for instrument in instruments
    ]
