from sqlalchemy import select
from sqlalchemy.orm import Session

from factory.registry.models import App, CostEvent, Run
from factory.registry.register import approve_build, register_app

REQUESTER_SUB = "11111111-1111-1111-1111-111111111111"

PLAN_RESULT = {
    "outcome": "proceed",
    "name": "Office Supply Request Tracker",
    "purpose": "Track office supply requests.",
    "blueprint_id": "streamlit-small",
    "complexity_score": 2,
    "score_justification": {"data_sources": "one"},
    "capabilities": [
        {"slug": "submit_request", "description": "Submit a supply request."},
        {"slug": "view_requests", "description": "View submitted requests."},
    ],
}


def _make_runs(db_session: Session) -> tuple[Run, Run]:
    plan_run = Run(
        kind="plan",
        requester_sub=REQUESTER_SUB,
        outcome="proceed",
        plan={"transcript": [], "result": PLAN_RESULT},
    )
    db_session.add(plan_run)
    db_session.commit()

    build_review_run = Run(
        kind="build_review",
        plan_run_id=plan_run.id,
        outcome="success",
        repo_path="/app/generated_apps/office-supply-request-tracker",
        container_port=9000,
    )
    db_session.add(build_review_run)
    db_session.commit()

    db_session.add(
        CostEvent(
            run_id=plan_run.id,
            stage="plan",
            model="claude-sonnet-4-5",
            input_tokens=10,
            cached_tokens=0,
            output_tokens=20,
            usd=0.01,
        )
    )
    db_session.add(
        CostEvent(
            run_id=build_review_run.id,
            stage="build",
            model="claude-sonnet-4-5",
            input_tokens=100,
            cached_tokens=0,
            output_tokens=200,
            usd=0.05,
        )
    )
    db_session.commit()
    db_session.refresh(plan_run)
    db_session.refresh(build_review_run)
    return plan_run, build_review_run


def test_register_app_creates_app_with_owner_and_capabilities(db_session: Session) -> None:
    plan_run, build_review_run = _make_runs(db_session)

    app = register_app(db_session, plan_run, build_review_run)

    assert app.slug == "office-supply-request-tracker"
    assert app.repo_path == "/app/generated_apps/office-supply-request-tracker"
    assert app.container_port == 9000
    assert {o.keycloak_sub for o in app.owners} == {REQUESTER_SUB}
    assert {(o.role) for o in app.owners} == {"business"}
    assert {c.slug for c in app.capabilities} == {"submit_request", "view_requests"}


def test_register_app_backfills_app_id_on_runs_and_cost_events(db_session: Session) -> None:
    plan_run, build_review_run = _make_runs(db_session)

    app = register_app(db_session, plan_run, build_review_run)

    assert plan_run.app_id == app.id
    assert build_review_run.app_id == app.id

    cost_events = db_session.scalars(
        select(CostEvent).where(CostEvent.run_id.in_([plan_run.id, build_review_run.id]))
    ).all()
    assert len(cost_events) == 2
    assert all(event.app_id == app.id for event in cost_events)


def test_register_app_links_capability_to_build_review_run(db_session: Session) -> None:
    plan_run, build_review_run = _make_runs(db_session)

    app = register_app(db_session, plan_run, build_review_run)

    assert all(c.added_by_run_id == build_review_run.id for c in app.capabilities)


def test_approve_build_sets_timestamp(db_session: Session) -> None:
    _, build_review_run = _make_runs(db_session)

    assert build_review_run.build_approved_at is None
    approve_build(db_session, build_review_run)
    assert build_review_run.build_approved_at is not None


def test_register_app_shows_up_via_app_query(db_session: Session) -> None:
    plan_run, build_review_run = _make_runs(db_session)
    register_app(db_session, plan_run, build_review_run)

    found = db_session.scalars(select(App).where(App.slug == "office-supply-request-tracker")).one()
    assert found.name == "Office Supply Request Tracker"
