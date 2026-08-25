from sqlalchemy.orm import Session

from factory.registry.models import App
from factory.registry.plan_runs import (
    append_turn,
    approve_plan,
    create_plan_run,
    finalize_run,
    get_plan_run,
    is_turn_cap_reached,
    record_plan_cost_events,
)

ALICE_SUB = "11111111-1111-1111-1111-111111111111"


def test_create_and_fetch_plan_run(db_session: Session) -> None:
    run = create_plan_run(db_session, ALICE_SUB)

    fetched = get_plan_run(db_session, run.id)

    assert fetched is not None
    assert fetched.requester_sub == ALICE_SUB
    assert fetched.kind == "plan"
    assert fetched.turns_used == 0
    assert fetched.plan == {"transcript": [], "result": None}


def test_append_turn_increments_count_and_transcript(db_session: Session) -> None:
    run = create_plan_run(db_session, ALICE_SUB)

    append_turn(db_session, run, "I need an app for X", "What does X need to track?")
    append_turn(db_session, run, "Just a name and a date", "Got it, one more question...")

    assert run.turns_used == 2
    assert len(run.plan["transcript"]) == 4
    assert run.plan["transcript"][0] == {"role": "user", "content": "I need an app for X"}


def test_is_turn_cap_reached() -> None:
    run = type("R", (), {"turns_used": 8})()
    assert is_turn_cap_reached(run, max_turns=8) is True
    run.turns_used = 7
    assert is_turn_cap_reached(run, max_turns=8) is False


def test_finalize_run_sets_outcome_and_app(db_session: Session) -> None:
    run = create_plan_run(db_session, ALICE_SUB)
    app = App(
        slug="expense-approval-tracker",
        name="Expense Approval Tracker",
        purpose="x",
        blueprint_id="streamlit-small",
        complexity_score=2,
        manifest={},
    )
    db_session.add(app)
    db_session.commit()

    finalize_run(
        db_session,
        run,
        {"outcome": "route_to_human", "reason": "overlaps_existing_app"},
        app_id=app.id,
    )

    fetched = get_plan_run(db_session, run.id)
    assert fetched.outcome == "route_to_human"
    assert fetched.app_id == app.id
    assert fetched.plan["result"]["reason"] == "overlaps_existing_app"


def test_approve_plan_sets_timestamp(db_session: Session) -> None:
    run = create_plan_run(db_session, ALICE_SUB)
    finalize_run(db_session, run, {"outcome": "proceed"})

    assert run.plan_approved_at is None
    approve_plan(db_session, run)
    assert run.plan_approved_at is not None


def test_record_plan_cost_events(db_session: Session) -> None:
    run = create_plan_run(db_session, ALICE_SUB)

    record_plan_cost_events(
        db_session,
        run,
        {
            "claude-sonnet-4-5": {
                "inputTokens": 1000,
                "outputTokens": 200,
                "cacheReadInputTokens": 500,
                "costUSD": 0.0123,
            }
        },
    )

    assert len(run.cost_events) == 1
    event = run.cost_events[0]
    assert event.stage == "plan"
    assert event.model == "claude-sonnet-4-5"
    assert event.input_tokens == 1000
    assert event.usd == 0.0123
