"""Autonomy mode endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.schemas.events import AutonomyMode, EventEnvelope, EventType

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/mode", tags=["mode"])

_VALID_TRANSITIONS: dict[AutonomyMode, set[AutonomyMode]] = {
    AutonomyMode.OBSERVE: {AutonomyMode.PAPER, AutonomyMode.ASSISTED},
    AutonomyMode.PAPER: {AutonomyMode.OBSERVE, AutonomyMode.ASSISTED},
    AutonomyMode.ASSISTED: {AutonomyMode.OBSERVE, AutonomyMode.PAPER},
    AutonomyMode.SEMI_AUTO: {AutonomyMode.OBSERVE, AutonomyMode.ASSISTED},
    AutonomyMode.SUPERVISED: {AutonomyMode.OBSERVE, AutonomyMode.ASSISTED},
}


class ModeChangeRequest(BaseModel):
    mode: AutonomyMode
    reason: str = ""


@router.get("")
async def get_mode(request: Request) -> dict:
    return {"mode": request.app.state.autonomy_mode.value}


@router.post("")
async def set_mode(body: ModeChangeRequest, request: Request) -> dict:
    current: AutonomyMode = request.app.state.autonomy_mode
    if body.mode == current:
        return {"mode": current.value}

    allowed = _VALID_TRANSITIONS.get(current, set())
    if body.mode not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot transition from {current.value!r} to {body.mode.value!r}",
        )

    now = datetime.now(UTC)
    await request.app.state.bus.publish(EventEnvelope(
        event_type=EventType.SYSTEM_MODE_CHANGED,
        source="operator",
        event_time=now,
        ingest_time=now,
        payload={
            "from_mode": current.value,
            "to_mode": body.mode.value,
            "actor": "operator",
            "reason": body.reason,
        },
    ))
    request.app.state.autonomy_mode = body.mode
    logger.info("mode.changed", from_mode=current.value, to_mode=body.mode.value)
    return {"mode": body.mode.value}
