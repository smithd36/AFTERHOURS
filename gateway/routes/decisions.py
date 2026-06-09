"""Decision lifecycle endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


@router.get("")
async def list_decisions(request: Request) -> dict:
    store = request.app.state.decision_store
    return {"decisions": list(store.values())}


@router.get("/pending")
async def list_pending(request: Request) -> dict:
    executor = request.app.state.executor
    return {"pending": executor.pending_decisions}


@router.post("/{decision_id}/execute")
async def execute_decision(decision_id: str, request: Request) -> dict:
    executor = request.app.state.executor
    ok = await executor.execute(decision_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Decision not found in pending queue")
    return {"status": "executed", "decision_id": decision_id}


@router.post("/{decision_id}/reject")
async def reject_decision(decision_id: str, request: Request) -> dict:
    executor = request.app.state.executor
    payload = executor._pending.pop(decision_id, None)
    if payload is None:
        raise HTTPException(status_code=404, detail="Decision not found in pending queue")
    return {"status": "rejected", "decision_id": decision_id}
