"""Ties one planner turn to Run persistence, the turn cap, and finalization side effects."""

import uuid

from pydantic import BaseModel
from sqlalchemy.orm import Session

from factory.agents.blueprint import load_blueprint
from factory.agents.plan_schema import IncompleteOutcome
from factory.agents.plan_session import run_planner_turn
from factory.agents.planner_settings import get_planner_settings
from factory.registry.models import App, FeatureRequest, Run
from factory.registry.plan_runs import (
    append_turn,
    create_plan_run,
    finalize_run,
    is_turn_cap_reached,
    record_plan_cost_events,
)
from factory.registry.queries import get_app_by_slug

PLANNER_BLUEPRINT_ID = "streamlit-small"


class PlanTurnView(BaseModel):
    run_id: uuid.UUID
    done: bool
    message: str
    outcome: dict | None
    turns_used: int


async def start_plan(
    session: Session,
    requester_sub: str,
    message: str,
    *,
    target_app_id: uuid.UUID | None = None,
    feature_request_id: uuid.UUID | None = None,
) -> PlanTurnView:
    run = create_plan_run(
        session,
        requester_sub,
        target_app_id=target_app_id,
        feature_request_id=feature_request_id,
    )
    return await _advance(session, run, message, is_first_turn=True)


async def continue_plan(session: Session, run: Run, message: str) -> PlanTurnView:
    if run.outcome is not None:
        raise ValueError("This plan has already been finalized.")
    return await _advance(session, run, message, is_first_turn=False)


async def _advance(
    session: Session, run: Run, message: str, *, is_first_turn: bool
) -> PlanTurnView:
    settings = get_planner_settings()
    blueprint = load_blueprint(PLANNER_BLUEPRINT_ID)
    target_app = session.get(App, run.app_id) if run.app_id else None

    result = await run_planner_turn(
        session_id=str(run.id),
        is_first_turn=is_first_turn,
        user_message=message,
        blueprint=blueprint,
        target_app=target_app,
    )
    append_turn(session, run, message, result.reply_text)
    if result.model_usage:
        record_plan_cost_events(session, run, result.model_usage)

    if result.outcome is not None:
        return _finalize(session, run, result.outcome, result.reply_text)

    if is_turn_cap_reached(run, settings.planner_max_turns):
        incomplete = IncompleteOutcome(
            turns_used=run.turns_used,
            still_needed=result.reply_text or "more information from the requester",
        ).model_dump()
        finalize_run(session, run, incomplete)
        return PlanTurnView(
            run_id=run.id,
            done=True,
            message="Turn limit reached before a plan could be finalized.",
            outcome=incomplete,
            turns_used=run.turns_used,
        )

    return PlanTurnView(
        run_id=run.id,
        done=False,
        message=result.reply_text,
        outcome=None,
        turns_used=run.turns_used,
    )


def _is_keycloak_sub(value: str) -> bool:
    """A real Keycloak ``sub`` claim is always a UUID (Keycloak issues them,
    never a client) — this is what lets us tell a genuine owner apart from
    stale test-fixture rows or a model-hallucinated username, independent of
    whatever happens to already be sitting in app_owners."""
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return True


def _validated_owner_sub(app, owner_sub: str) -> str:
    """Named owners must be real — a model-supplied owner_sub for an overlap is
    trusted only if it's both UUID-shaped and actually an owner of the app it
    claims to overlap with; otherwise substitute a real one so routing never
    names a fabricated (or, e.g., stale non-UUID test-fixture) person.

    The UUID check matters even when owner_sub matches something already in
    app.owners: legacy or hand-inserted rows can carry non-UUID values, and
    trusting "it's in the table" alone would let that garbage validate a
    garbage answer right back."""
    valid_owners = [o for o in app.owners if _is_keycloak_sub(o.keycloak_sub)]
    if _is_keycloak_sub(owner_sub) and any(o.keycloak_sub == owner_sub for o in valid_owners):
        return owner_sub
    fallback = next((o for o in valid_owners if o.role == "business"), None) or next(
        iter(valid_owners), None
    )
    return fallback.keycloak_sub if fallback else owner_sub


def _finalize(session: Session, run: Run, outcome: dict, reply_text: str) -> PlanTurnView:
    kind = outcome["outcome"]
    # Preserve run.app_id by default: for a feature-request pickup, it was
    # already set to the target app at creation, and a "proceed" outcome here
    # must not clobber that back to None. The branches below only override it
    # for outcomes that resolve a *different* app lookup (route_to_human,
    # feature_request).
    app_id = run.app_id

    if kind == "route_to_human" and outcome.get("overlapping_app_slug"):
        app = get_app_by_slug(session, outcome["overlapping_app_slug"])
        app_id = app.id if app else None
        if app is not None:
            outcome["owner_sub"] = _validated_owner_sub(app, outcome["owner_sub"])

    elif kind == "feature_request":
        app = get_app_by_slug(session, outcome["target_app_slug"])
        if app is None:
            return PlanTurnView(
                run_id=run.id,
                done=False,
                message=(
                    f"I couldn't find an app with slug '{outcome['target_app_slug']}' in the "
                    "registry — which existing app is this a change to?"
                ),
                outcome=None,
                turns_used=run.turns_used,
            )
        app_id = app.id

    finalize_run(session, run, outcome, app_id=app_id)

    if kind == "feature_request":
        session.add(
            FeatureRequest(
                app_id=app_id,
                requester_sub=run.requester_sub,
                description=outcome["description"],
            )
        )
        session.commit()

    return PlanTurnView(
        run_id=run.id,
        done=True,
        message=reply_text,
        outcome=outcome,
        turns_used=run.turns_used,
    )
