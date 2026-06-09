"""Emergency halt endpoint — forces system to OBSERVE mode."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from core.schemas.events import AutonomyMode, EventEnvelope, EventType

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/halt", tags=["halt"])


class HaltRequest(BaseModel):
    reason: str = "operator_halt"


@router.post("")
async def halt(body: HaltRequest, request: Request) -> dict:
    current: AutonomyMode = request.app.state.autonomy_mode
    now = datetime.now(UTC)

    await request.app.state.bus.publish(EventEnvelope(
        event_type=EventType.RISK_HALT,
        source="operator",
        event_time=now,
        ingest_time=now,
        payload={
            "reason": body.reason,
            "scope": "all",
            "actor": "operator",
        },
    ))

    if current != AutonomyMode.OBSERVE:
        await request.app.state.bus.publish(EventEnvelope(
            event_type=EventType.SYSTEM_MODE_CHANGED,
            source="operator",
            event_time=now,
            ingest_time=now,
            payload={
                "from_mode": current.value,
                "to_mode": AutonomyMode.OBSERVE.value,
                "actor": "operator",
                "reason": body.reason,
            },
        ))
        request.app.state.autonomy_mode = AutonomyMode.OBSERVE

    logger.warning("halt.activated", reason=body.reason, from_mode=current.value)
    return {"status": "halted", "mode": AutonomyMode.OBSERVE.value}
