"""Event history endpoints — UI panel rehydration from the audit log."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from core.schemas.events import EventType
from core.schemas.signal import SignalType

router = APIRouter(prefix="/api/events", tags=["events"])

_MAX_LIMIT = 500
_VALID_TYPES = {t.value for t in EventType}
_VALID_SIGNAL_TYPES = {t.value for t in SignalType}


@router.get("/recent")
async def recent_events(
    request: Request,
    types: str = Query(..., description="Comma-separated event types, e.g. signal.created"),
    limit: int = Query(200, ge=1, le=_MAX_LIMIT),
    signal_types: str | None = Query(
        None,
        description="Comma-separated signal subtypes (payload `type`) to restrict to, "
        "e.g. insider_tx,supply_chain — gives sparse alt-data its own backfill window.",
    ),
) -> dict[str, list[dict[str, Any]]]:
    """
    The newest `limit` events of the given types, oldest first, so clients
    can replay them through the same handlers used for live WS events.
    """
    requested = [t.strip() for t in types.split(",") if t.strip()]
    unknown = [t for t in requested if t not in _VALID_TYPES]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown event types: {unknown}")

    payload_type: list[str] | None = None
    if signal_types:
        payload_type = [t.strip() for t in signal_types.split(",") if t.strip()]
        bad = [t for t in payload_type if t not in _VALID_SIGNAL_TYPES]
        if bad:
            raise HTTPException(status_code=422, detail=f"Unknown signal types: {bad}")

    store = request.app.state.event_store
    envelopes = await store.recent(requested, limit=limit, payload_type=payload_type)
    return {"events": [e.model_dump(mode="json") for e in envelopes]}
