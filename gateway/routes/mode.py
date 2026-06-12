"""Autonomy mode endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.mode import InvalidModeTransition, ModeController
from core.schemas.events import AutonomyMode

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/mode", tags=["mode"])


class ModeChangeRequest(BaseModel):
    mode: AutonomyMode
    reason: str = ""


@router.get("")
async def get_mode(request: Request) -> dict:
    controller: ModeController = request.app.state.mode_controller
    return {"mode": controller.current.value}


@router.post("")
async def set_mode(body: ModeChangeRequest, request: Request) -> dict:
    # The controller owns the value, validates the transition, and publishes the
    # audit event atomically — the route no longer mutates mode state itself.
    controller: ModeController = request.app.state.mode_controller
    try:
        new_mode = await controller.set(body.mode, actor="operator", reason=body.reason)
    except InvalidModeTransition as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"mode": new_mode.value}
