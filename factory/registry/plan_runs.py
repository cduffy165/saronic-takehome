"""Persistence for Plan-stage runs: the transcript, turn count, outcome, and cost."""

import datetime
import uuid
from typing import Any

from sqlalchemy.orm import Session

from factory.registry.models import CostEvent, Run


def create_plan_run(
    session: Session,
    requester_sub: str,
    *,
    target_app_id: uuid.UUID | None = None,
    feature_request_id: uuid.UUID | None = None,
) -> Run:
    """``target_app_id`` marks a feature-request pickup: Build/Review then
    modify that app's existing repo instead of writing a fresh one."""
    run = Run(
        kind="plan",
        requester_sub=requester_sub,
        turns_used=0,
        plan={"transcript": [], "result": None},
        app_id=target_app_id,
        feature_request_id=feature_request_id,
    )
    session.add(run)
    session.commit()
    return run


def get_plan_run(session: Session, run_id: uuid.UUID) -> Run | None:
    return session.get(Run, run_id)


def is_turn_cap_reached(run: Run, max_turns: int) -> bool:
    return run.turns_used >= max_turns


def append_turn(session: Session, run: Run, user_message: str, assistant_message: str) -> None:
    plan = dict(run.plan or {"transcript": [], "result": None})
    transcript = list(plan.get("transcript", []))
    transcript.append({"role": "user", "content": user_message})
    transcript.append({"role": "assistant", "content": assistant_message})
    plan["transcript"] = transcript
    run.plan = plan
    run.turns_used += 1
    session.commit()


def finalize_run(
    session: Session, run: Run, outcome: dict[str, Any], app_id: uuid.UUID | None = None
) -> None:
    plan = dict(run.plan or {"transcript": [], "result": None})
    plan["result"] = outcome
    run.plan = plan
    run.outcome = outcome["outcome"]
    run.app_id = app_id
    session.commit()


def approve_plan(session: Session, run: Run) -> None:
    run.plan_approved_at = datetime.datetime.now(datetime.UTC)
    session.commit()


def record_plan_cost_events(session: Session, run: Run, model_usage: dict[str, Any]) -> None:
    """Record one cost_events row per model used in a planner turn."""
    for model_name, usage in model_usage.items():
        session.add(
            CostEvent(
                run_id=run.id,
                app_id=run.app_id,
                stage="plan",
                model=model_name,
                input_tokens=usage.get("inputTokens", 0),
                cached_tokens=usage.get("cacheReadInputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
                usd=usage.get("costUSD", 0.0),
            )
        )
    session.commit()
