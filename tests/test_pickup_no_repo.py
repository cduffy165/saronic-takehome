import asyncio

from sqlalchemy.orm import Session

from factory.agents.build_review_orchestrator import run_build_and_review
from factory.registry.models import App, Run


def test_pickup_against_app_with_no_repo_on_disk_fails_legibly(db_session: Session) -> None:
    """Seeded apps (until M8) have no real repo_path directory — pickup must
    fail with a clear finding, not crash or spend on a Build call."""
    app = App(
        slug="seeded-app-no-repo",
        name="Seeded App",
        purpose="x",
        blueprint_id="streamlit-small",
        complexity_score=1,
        manifest={},
        repo_path="/app/generated_apps/does-not-exist-on-disk",
        container_port=None,
    )
    db_session.add(app)
    db_session.commit()

    plan_run = Run(
        kind="plan",
        requester_sub="alice",
        outcome="proceed",
        app_id=app.id,
        plan={
            "transcript": [],
            "result": {
                "outcome": "proceed",
                "name": "Add a thing",
                "purpose": "x",
                "blueprint_id": "streamlit-small",
                "complexity_score": 1,
                "score_justification": {},
                "capabilities": [{"slug": "new_cap", "description": "x"}],
            },
        },
    )
    db_session.add(plan_run)
    db_session.commit()

    result = asyncio.run(run_build_and_review(db_session, plan_run))

    assert result.success is False
    assert result.attempts == 0
    assert any(f.category == "missing_repo" for f in result.findings)
