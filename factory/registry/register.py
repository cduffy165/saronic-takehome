"""Register: plain code, no LLM. Writes the App row once a human approves a
successful build (Gate 2) — this is the only place App rows get created."""

import datetime

from sqlalchemy.orm import Session

from factory.registry.models import App, AppOwner, Capability, Run
from factory.registry.slug import slugify


def approve_build(session: Session, build_review_run: Run) -> None:
    build_review_run.build_approved_at = datetime.datetime.now(datetime.UTC)
    session.commit()


def register_app(session: Session, plan_run: Run, build_review_run: Run) -> App:
    plan = plan_run.plan["result"]

    app = App(
        slug=slugify(plan["name"]),
        name=plan["name"],
        purpose=plan["purpose"],
        blueprint_id=plan["blueprint_id"],
        status="active",
        complexity_score=plan["complexity_score"],
        manifest=plan,
        repo_path=build_review_run.repo_path,
        container_port=build_review_run.container_port,
    )
    session.add(app)
    session.flush()  # assigns app.id

    session.add(AppOwner(app_id=app.id, keycloak_sub=plan_run.requester_sub, role="business"))
    for capability in plan["capabilities"]:
        session.add(
            Capability(
                app_id=app.id,
                slug=capability["slug"],
                description=capability["description"],
                added_by_run_id=build_review_run.id,
            )
        )

    plan_run.app_id = app.id
    build_review_run.app_id = app.id
    for run in (plan_run, build_review_run):
        for event in run.cost_events:
            event.app_id = app.id

    session.commit()
    return app
