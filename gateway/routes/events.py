"""Event history endpoints — UI panel rehydration from the audit log."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from core.schemas.events import EventType

router = APIRouter(prefix="/api/events", tags=["events"])

_MAX_LIMIT = 500
_VALID_TYPES = {t.value for t in EventType}


@router.get("/recent")
async def recent_events(
    request: Request,
    types: str = Query(..., description="Comma-separated event types, e.g. signal.created"),
    limit: int = Query(200, ge=1, le=_MAX_LIMIT),
) -> dict[str, list[dict[str, Any]]]:
    """
    The newest `limit` events of the given types, oldest first, so clients
    can replay them through the same handlers used for live WS events.
    """
    requested = [t.strip() for t in types.split(",") if t.strip()]
    unknown = [t for t in requested if t not in _VALID_TYPES]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown event types: {unknown}")

    store = request.app.state.event_store
    envelopes = await store.recent(requested, limit=limit)
    return {"events": [e.model_dump(mode="json") for e in envelopes]}
