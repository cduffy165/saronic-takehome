"""FastAPI entrypoint for the app factory's orchestration API."""

import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from factory.agents.build_review_orchestrator import BuildReviewView, run_build_and_review
from factory.agents.plan_orchestrator import PlanTurnView, continue_plan, start_plan
from factory.api.auth import get_verified_sub
from factory.registry.db import get_session
from factory.registry.models import Run
from factory.registry.plan_runs import approve_plan, get_plan_run

app = FastAPI(title="app-factory-api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class StartPlanRequest(BaseModel):
    message: str


class ContinuePlanRequest(BaseModel):
    message: str


class RunView(BaseModel):
    run_id: uuid.UUID
    requester_sub: str | None
    turns_used: int
    outcome: dict | None
    transcript: list[dict]
    plan_approved_at: str | None


def _get_owned_run(session: Session, run_id: uuid.UUID, verified_sub: str) -> Run:
    """Fetches a run and enforces that the caller is the one who started it —
    a valid token proves who you are, not that you may act on someone else's
    plan run."""
    run = get_plan_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such plan run.")
    if run.requester_sub != verified_sub:
        raise HTTPException(status_code=403, detail="This plan run belongs to a different user.")
    return run


@app.post("/plans", response_model=PlanTurnView)
async def create_plan(
    body: StartPlanRequest,
    session: Annotated[Session, Depends(get_session)],
    verified_sub: Annotated[str, Depends(get_verified_sub)],
) -> PlanTurnView:
    return await start_plan(session, verified_sub, body.message)


@app.post("/plans/{run_id}/messages", response_model=PlanTurnView)
async def send_plan_message(
    run_id: uuid.UUID,
    body: ContinuePlanRequest,
    session: Annotated[Session, Depends(get_session)],
    verified_sub: Annotated[str, Depends(get_verified_sub)],
) -> PlanTurnView:
    run = _get_owned_run(session, run_id, verified_sub)
    try:
        return await continue_plan(session, run, body.message)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/plans/{run_id}", response_model=RunView)
def get_plan(
    run_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    verified_sub: Annotated[str, Depends(get_verified_sub)],
) -> RunView:
    run = _get_owned_run(session, run_id, verified_sub)
    plan = run.plan or {}
    return RunView(
        run_id=run.id,
        requester_sub=run.requester_sub,
        turns_used=run.turns_used,
        outcome=plan.get("result"),
        transcript=plan.get("transcript", []),
        plan_approved_at=run.plan_approved_at.isoformat() if run.plan_approved_at else None,
    )


@app.post("/plans/{run_id}/approve", response_model=BuildReviewView)
async def approve_plan_endpoint(
    run_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    verified_sub: Annotated[str, Depends(get_verified_sub)],
) -> BuildReviewView:
    run = _get_owned_run(session, run_id, verified_sub)
    if run.outcome != "proceed":
        raise HTTPException(status_code=409, detail="Only a 'proceed' plan can be approved.")
    if run.plan_approved_at is not None:
        raise HTTPException(status_code=409, detail="This plan was already approved.")
    approve_plan(session, run)
    return await run_build_and_review(session, run)
