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
from factory.registry.models import App, FeatureRequest, Run
from factory.registry.plan_runs import approve_plan, get_plan_run
from factory.registry.queries import find_open_feature_requests_for_owner
from factory.registry.register import (
    approve_build,
    mark_feature_request_picked_up,
    register_app,
    register_feature,
)

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


class RegisterView(BaseModel):
    app_id: uuid.UUID
    slug: str
    name: str


@app.post("/builds/{run_id}/approve", response_model=RegisterView)
def approve_build_endpoint(
    run_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    verified_sub: Annotated[str, Depends(get_verified_sub)],
) -> RegisterView:
    build_review_run = session.get(Run, run_id)
    if build_review_run is None or build_review_run.kind != "build_review":
        raise HTTPException(status_code=404, detail="No such build run.")

    plan_run = (
        session.get(Run, build_review_run.plan_run_id) if build_review_run.plan_run_id else None
    )
    if plan_run is None or plan_run.requester_sub != verified_sub:
        raise HTTPException(status_code=403, detail="This build belongs to a different user.")

    if build_review_run.outcome != "success":
        raise HTTPException(status_code=409, detail="Only a successful build can be registered.")
    if build_review_run.build_approved_at is not None:
        raise HTTPException(status_code=409, detail="This build was already registered.")

    approve_build(session, build_review_run)

    if build_review_run.app_id is not None:
        # Feature-request pickup (M7): app_id was set at plan creation, not by
        # a prior registration — append to the existing app instead of
        # creating a new one.
        existing_app = session.get(App, build_review_run.app_id)
        app_row = register_feature(session, plan_run, build_review_run, existing_app)
    else:
        app_row = register_app(session, plan_run, build_review_run)
    return RegisterView(app_id=app_row.id, slug=app_row.slug, name=app_row.name)


class FeatureRequestView(BaseModel):
    id: uuid.UUID
    app_id: uuid.UUID
    app_slug: str
    requester_sub: str
    description: str
    status: str


@app.get("/feature-requests", response_model=list[FeatureRequestView])
def list_feature_requests(
    session: Annotated[Session, Depends(get_session)],
    verified_sub: Annotated[str, Depends(get_verified_sub)],
) -> list[FeatureRequestView]:
    requests = find_open_feature_requests_for_owner(session, verified_sub)
    return [
        FeatureRequestView(
            id=fr.id,
            app_id=fr.app_id,
            app_slug=fr.app.slug,
            requester_sub=fr.requester_sub,
            description=fr.description,
            status=fr.status,
        )
        for fr in requests
    ]


@app.post("/feature-requests/{request_id}/pickup", response_model=PlanTurnView)
async def pickup_feature_request(
    request_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    verified_sub: Annotated[str, Depends(get_verified_sub)],
) -> PlanTurnView:
    feature_request = session.get(FeatureRequest, request_id)
    if feature_request is None:
        raise HTTPException(status_code=404, detail="No such feature request.")
    if verified_sub not in {o.keycloak_sub for o in feature_request.app.owners}:
        raise HTTPException(
            status_code=403, detail="Only an owner of the target app can pick this up."
        )
    if feature_request.status == "resolved":
        raise HTTPException(status_code=409, detail="This request was already resolved.")

    mark_feature_request_picked_up(session, feature_request)
    return await start_plan(
        session,
        verified_sub,
        feature_request.description,
        target_app_id=feature_request.app_id,
        feature_request_id=feature_request.id,
    )
