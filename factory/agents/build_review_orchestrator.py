"""Build -> deterministic gate -> Review, with one retry, then git commit + container run.

Ordering is a safety property, not just convention: write files, then run the
required-files check and the secrets scan, then Review — nothing generated is
ever git-committed or run as a container until it clears all three.
"""

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from factory.agents.build_review_schema import ReviewFinding
from factory.agents.build_session import run_build_turn
from factory.agents.build_settings import get_build_settings
from factory.agents.container_runtime import allocate_port, build_and_run, get_docker_client
from factory.agents.review_session import run_review_turn
from factory.agents.secrets_scanner import scan_directory
from factory.registry.models import CostEvent, Run

GENERATED_APPS_DIR = Path(__file__).resolve().parents[2] / "generated_apps"
REQUIRED_FILES = ["app.py", "Dockerfile", "README.md"]


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "app"


class BuildReviewView(BaseModel):
    run_id: uuid.UUID
    success: bool
    attempts: int
    findings: list[ReviewFinding]
    summary: str
    repo_path: str | None = None
    container_port: int | None = None


def _reset_app_dir(app_dir: Path) -> None:
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)


def _check_required_files(app_dir: Path) -> list[ReviewFinding]:
    missing = [f for f in REQUIRED_FILES if not (app_dir / f).is_file()]
    return [
        ReviewFinding(
            severity="high", category="missing_file", description=f"Missing required file: {f}"
        )
        for f in missing
    ]


def _feedback_text(findings: list[ReviewFinding]) -> str:
    return "\n".join(f"- [{f.severity}] {f.category}: {f.description}" for f in findings)


def _chown_to_host_user(app_dir: Path, uid: int, gid: int) -> None:
    """The api container runs as root; without this, generated_apps/<slug> is
    written root-owned and a non-root host dev can't edit or even delete it."""
    os.chown(app_dir, uid, gid)
    for path in app_dir.rglob("*"):
        os.chown(path, uid, gid)


def _record_cost(session: Session, run: Run, stage: str, model_usage: dict[str, Any]) -> None:
    for model_name, usage in model_usage.items():
        session.add(
            CostEvent(
                run_id=run.id,
                app_id=run.app_id,
                stage=stage,
                model=model_name,
                input_tokens=usage.get("inputTokens", 0),
                cached_tokens=usage.get("cacheReadInputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
                usd=usage.get("costUSD", 0.0),
            )
        )
    session.commit()


def _git_init_and_commit(app_dir: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=app_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=app_dir, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=App Factory",
            "-c",
            "user.email=factory@localhost",
            "commit",
            "-q",
            "-m",
            "Initial build",
        ],
        cwd=app_dir,
        check=True,
    )


def _dockerize(app_dir: Path, slug: str) -> tuple[str, int]:
    client = get_docker_client()
    port = allocate_port(client)
    build_and_run(client, app_dir, slug, port)
    return str(app_dir), port


async def run_build_and_review(session: Session, plan_run: Run) -> BuildReviewView:
    settings = get_build_settings()
    plan = plan_run.plan["result"]
    slug = slugify(plan["name"])
    app_dir = GENERATED_APPS_DIR / slug

    build_review_run = Run(kind="build_review", plan_run_id=plan_run.id, app_id=plan_run.app_id)
    session.add(build_review_run)
    session.commit()

    all_findings: list[ReviewFinding] = []
    feedback: str | None = None

    for attempt in range(1, settings.max_build_review_attempts + 1):
        _reset_app_dir(app_dir)

        build_result = await run_build_turn(app_dir=app_dir, plan=plan, feedback=feedback)
        _record_cost(session, build_review_run, "build", build_result.model_usage)

        gate_findings = _check_required_files(app_dir) + scan_directory(app_dir)
        if gate_findings:
            all_findings = gate_findings
            feedback = _feedback_text(gate_findings)
            _chown_to_host_user(app_dir, settings.host_uid, settings.host_gid)
            continue

        review_turn = await run_review_turn(app_dir=app_dir)
        _record_cost(session, build_review_run, "review", review_turn.model_usage)

        if review_turn.result is None:
            all_findings = [
                ReviewFinding(
                    severity="high",
                    category="review_error",
                    description="Review did not return a structured result.",
                )
            ]
            feedback = _feedback_text(all_findings)
            _chown_to_host_user(app_dir, settings.host_uid, settings.host_gid)
            continue

        if review_turn.result.verdict != "pass":
            all_findings = review_turn.result.findings
            feedback = _feedback_text(all_findings)
            _chown_to_host_user(app_dir, settings.host_uid, settings.host_gid)
            continue

        try:
            # git runs as root (this container's user) against a still
            # root-owned directory — chowning to the host user has to wait
            # until after git is done, or git's own dubious-ownership check
            # refuses to operate on a repo it doesn't own (observed live).
            _git_init_and_commit(app_dir)
            repo_path, container_port = _dockerize(app_dir, slug)
        except Exception as exc:  # noqa: BLE001 - any docker/git failure is a retryable build failure
            all_findings = [
                ReviewFinding(
                    severity="high",
                    category="build_failed",
                    description=f"git/docker step failed: {exc}",
                )
            ]
            feedback = _feedback_text(all_findings)
            continue
        finally:
            _chown_to_host_user(app_dir, settings.host_uid, settings.host_gid)

        build_review_run.outcome = "success"
        build_review_run.repo_path = repo_path
        build_review_run.container_port = container_port
        build_review_run.review = {
            "attempts": attempt,
            "findings": [f.model_dump() for f in review_turn.result.findings],
            "summary": review_turn.result.summary,
        }
        session.commit()
        return BuildReviewView(
            run_id=build_review_run.id,
            success=True,
            attempts=attempt,
            findings=review_turn.result.findings,
            summary=review_turn.result.summary,
            repo_path=repo_path,
            container_port=container_port,
        )

    build_review_run.outcome = "failed"
    build_review_run.review = {
        "attempts": settings.max_build_review_attempts,
        "findings": [f.model_dump() for f in all_findings],
        "summary": "Exhausted retries without a passing review.",
    }
    session.commit()
    return BuildReviewView(
        run_id=build_review_run.id,
        success=False,
        attempts=settings.max_build_review_attempts,
        findings=all_findings,
        summary="Exhausted retries without a passing review.",
    )
