"""Emergency halt endpoint — forces system to OBSERVE mode."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from core.mode import ModeController
from core.schemas.events import AutonomyMode

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/halt", tags=["halt"])


class HaltRequest(BaseModel):
    reason: str = "operator_halt"


@router.post("")
async def halt(body: HaltRequest, request: Request) -> dict:
    # The controller forces OBSERVE and publishes risk.halt (+ an audited
    # mode-change when needed) atomically, so consumers can't observe a window
    # where the mode and the kill switch disagree.
    controller: ModeController = request.app.state.mode_controller
    await controller.halt(reason=body.reason, actor="operator")
    logger.warning("halt.activated", reason=body.reason)
    return {"status": "halted", "mode": AutonomyMode.OBSERVE.value}
