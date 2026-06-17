"""Discovery Engine (Phase 6B, ADR-012): multi-source opportunity surfacing.

This package is the scoring core — pure, deterministic functions that fold
weak, heterogeneous signals into ranked, explained candidates. The on-demand
projection and `/api/discovery` route (6B.1b) sit on top of these.
"""

from .analyst import AIAnalyst, DiscoveryAnalysis
from .contributions import Contribution
from .engine import build_candidates
from .extract import contributions_from_signal
from .resolve import resolve_instruments
from .score import Candidate, ScoredContribution, score_all, score_instrument
from .settings import DiscoverySettings

__all__ = [
    "AIAnalyst",
    "Candidate",
    "Contribution",
    "DiscoveryAnalysis",
    "DiscoverySettings",
    "ScoredContribution",
    "build_candidates",
    "contributions_from_signal",
    "resolve_instruments",
    "score_all",
    "score_instrument",
]
