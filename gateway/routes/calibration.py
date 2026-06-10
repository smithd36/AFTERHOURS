"""Calibration report and autonomy-gate readiness endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/calibration", tags=["calibration"])


@router.get("")
async def get_calibration(request: Request) -> dict[str, Any]:
    """ECE + reliability buckets, overall and per autonomy mode."""
    return request.app.state.calibration_engine.report()  # type: ignore[no-any-return]


@router.get("/gates")
async def get_gates(request: Request) -> dict[str, Any]:
    """Appendix B graduation-gate readiness (measurable criteria + deferred list)."""
    return request.app.state.gate_tracker.report()  # type: ignore[no-any-return]
