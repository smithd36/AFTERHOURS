"""
The conviction-scoring core (ADR-012): fold an instrument's Contributions into
a single opportunity score in [0, 1] — confluence, not sum.

Two-level combine:
  1. **Within a factor → max.** Correlated sources in the same family (five
     articles, three insiders) collapse to one vote; they must not compound.
  2. **Across factors → noisy-OR** (``1 - Π(1 - mᵢ)``). Independent families
     accumulate with diminishing returns, so two distinct weak factors outrank
     one loud one. A confluence bonus rewards ≥2 agreeing positive families.

Each contribution is weighted by its factor and decayed by age before combining;
negative (bearish) evidence is combined the same way and subtracted. Pure and
deterministic — the scoring half of the on-demand projection (ADR-011 pattern).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .contributions import Contribution
from .settings import DiscoverySettings

_SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True)
class ScoredContribution:
    factor: str
    weighted: float  # signed weight × decay × value actually fed into the score
    age_days: float
    summary: str
    source: str


@dataclass(frozen=True)
class Candidate:
    instrument: str
    score: float  # [0, 1]
    factors: tuple[str, ...]  # distinct positive factors (the confluence set)
    contributions: tuple[ScoredContribution, ...]  # strongest-first; the "why"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _noisy_or(mags: Iterable[float]) -> float:
    product = 1.0
    for m in mags:
        product *= 1.0 - _clamp01(m)
    return 1.0 - product


def _decay(age_days: float, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 1.0
    return float(0.5 ** (max(0.0, age_days) / half_life_days))


def score_instrument(
    instrument: str,
    contribs: list[Contribution],
    *,
    now: datetime,
    settings: DiscoverySettings,
) -> Candidate:
    scored: list[ScoredContribution] = []
    # Per factor, the strongest positive / negative weighted magnitude (max =
    # collapse correlated duplicates).
    pos_by_factor: dict[str, float] = defaultdict(float)
    neg_by_factor: dict[str, float] = defaultdict(float)

    for c in contribs:
        age_days = (now - c.event_time).total_seconds() / _SECONDS_PER_DAY
        decay = _decay(age_days, settings.half_life(c.factor))
        weighted = max(-1.0, min(1.0, settings.weight(c.factor) * decay * c.value))
        scored.append(
            ScoredContribution(
                factor=c.factor,
                weighted=weighted,
                age_days=age_days,
                summary=c.summary,
                source=c.source,
            )
        )
        bucket = pos_by_factor if weighted >= 0 else neg_by_factor
        bucket[c.factor] = max(bucket[c.factor], abs(weighted))

    positive = _noisy_or(pos_by_factor.values())
    negative = _noisy_or(neg_by_factor.values())
    score = positive - negative

    distinct_pos = tuple(sorted(f for f, m in pos_by_factor.items() if m > 0))
    if len(distinct_pos) >= 2:
        # Saturating bonus: lifts toward 1 without ever exceeding it.
        score += settings.confluence_bonus * (1.0 - score)

    scored.sort(key=lambda s: abs(s.weighted), reverse=True)
    return Candidate(
        instrument=instrument,
        score=_clamp01(score),
        factors=distinct_pos,
        contributions=tuple(scored),
    )


def score_all(
    contribs: Iterable[Contribution],
    *,
    now: datetime,
    settings: DiscoverySettings,
) -> list[Candidate]:
    """Group contributions by instrument, score each, return strongest-first.

    Threshold and top-k filtering are the engine's job (the projection); this
    returns every scored instrument so callers can rank/cut as they choose.
    """
    by_instrument: dict[str, list[Contribution]] = defaultdict(list)
    for c in contribs:
        by_instrument[c.instrument].append(c)

    candidates = [
        score_instrument(instrument, items, now=now, settings=settings)
        for instrument, items in by_instrument.items()
    ]
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
