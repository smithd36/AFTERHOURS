"""
The discovery projection: rank *unwatched* instruments by confluence score,
computed on demand over the persisted event store (ADR-012, pull-first).

No stateful subscriber and no new event type — it replays `signal.created` from
a lookback window exactly as `analytics/` replays fills for the equity curve
(ADR-011). Watched instruments are excluded: discovery is the pre-watchlist
funnel, so a name already on the watchlist is the pipeline's job, not its.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from core.bus.store import EventStore
from core.schemas.events import EventType

from .extract import contributions_from_signal
from .score import Candidate, score_all
from .settings import DiscoverySettings


async def build_candidates(
    store: EventStore,
    *,
    watched: set[str],
    now: datetime,
    settings: DiscoverySettings,
) -> list[Candidate]:
    """Top-k unwatched candidates scoring at/above the threshold, strongest-first."""
    start = now - timedelta(days=settings.window_days)
    signals = await store.range([EventType.SIGNAL_CREATED.value], start=start)

    watched_keys = {w.upper() for w in watched}
    contribs = [
        c
        for env in signals
        for c in contributions_from_signal(env)
        if c.instrument not in watched_keys
    ]

    ranked = score_all(contribs, now=now, settings=settings)
    return [c for c in ranked if c.score >= settings.threshold][: settings.top_k]
