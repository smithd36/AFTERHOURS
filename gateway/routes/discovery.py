"""Ranked discovery candidates — the Phase 6B opportunity feed (ADR-012).

Read-side projection: replays `signal.created` on demand, scores unwatched
instruments by confluence, returns the ranked feed. No discovery state on
app.state beyond the (cheap) settings — the event store is the state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from discovery import AIAnalyst, DiscoverySettings, build_candidates
from discovery.analyst import DiscoveryAnalysis
from discovery.score import Candidate
from reasoning.llm.base import LLMProvider
from watchlist import WatchlistManager

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


def _serialize(c: Candidate) -> dict[str, Any]:
    return {
        "instrument": c.instrument,
        "score": round(c.score, 4),
        "factors": list(c.factors),
        "contributions": [
            {
                "factor": sc.factor,
                "weight": round(sc.weighted, 4),
                "age_days": round(sc.age_days, 2),
                "summary": sc.summary,
                "source": sc.source,
            }
            for sc in c.contributions
        ],
    }


@router.get("")
async def get_discovery(request: Request) -> dict[str, Any]:
    store = request.app.state.event_store
    manager: WatchlistManager = request.app.state.watchlist_manager
    settings: DiscoverySettings = request.app.state.discovery_settings

    now = datetime.now(UTC)
    candidates = await build_candidates(
        store,
        watched=set(manager.active_instruments),
        now=now,
        settings=settings,
    )
    return {
        "generated_at": now.isoformat(),
        "candidates": [_serialize(c) for c in candidates],
    }


def _serialize_analysis(a: DiscoveryAnalysis) -> dict[str, Any]:
    return {
        "instrument": a.instrument,
        "thesis": a.thesis,
        "risks": a.risks,
        "evidence_summary": a.evidence_summary,
        "suggested_step": a.suggested_step,
    }


@router.get("/{instrument}/analysis")
async def analyze_candidate(instrument: str, request: Request) -> dict[str, Any]:
    """LLM explain + counter-signals for one candidate (ADR-012).

    Lazy and operator-triggered — one cached, throttled call per request, never
    across the whole feed. The candidate is rebuilt server-side rather than
    trusting client-sent evidence.
    """
    store = request.app.state.event_store
    manager: WatchlistManager = request.app.state.watchlist_manager
    settings: DiscoverySettings = request.app.state.discovery_settings
    provider: LLMProvider = request.app.state.llm_provider

    now = datetime.now(UTC)
    candidates = await build_candidates(
        store, watched=set(manager.active_instruments), now=now, settings=settings
    )
    target = next(
        (c for c in candidates if c.instrument == instrument.upper()), None
    )
    if target is None:
        raise HTTPException(status_code=404, detail=f"{instrument} is not a current candidate")

    analyst = AIAnalyst(provider, max_tokens=settings.analysis_max_tokens)
    try:
        analysis = await analyst.analyze(target)
    except Exception as exc:  # provider/network/keys — degrade, don't 500
        raise HTTPException(status_code=503, detail="analyst unavailable") from exc
    if analysis is None:
        raise HTTPException(status_code=502, detail="analyst returned no usable result")

    return _serialize_analysis(analysis)
