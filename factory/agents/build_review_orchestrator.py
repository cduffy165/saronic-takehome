"""Build -> deterministic gate -> Review, with one retry, then git commit + container run.

Ordering is a safety property, not just convention: write files, then run the
required-files check and the secrets scan, then Review — nothing generated is
ever git-committed or run as a container until it clears all three.

Two modes: a fresh app (plan_run.app_id is None), or a feature-request pickup
modifying an app that already exists — plan_run.app_id is set to the target
app in that case. The pickup path never wipes the existing directory; a
failed attempt is discarded via `git checkout`/`clean`, not `rm -rf`.
"""

import os
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
from factory.agents.gitea_client import get_gitea_settings
from factory.agents.gitea_client import push as push_to_gitea
from factory.agents.review_session import run_review_turn
from factory.agents.secrets_scanner import scan_directory as scan_for_secrets
from factory.agents.static_analysis import scan_directory as scan_statically
from factory.registry.models import App, CostEvent, Run
from factory.registry.slug import slugify

GENERATED_APPS_DIR = Path(__file__).resolve().parents[2] / "generated_apps"
REQUIRED_FILES = ["app.py", "Dockerfile", "README.md"]


class BuildReviewView(BaseModel):
    run_id: uuid.UUID
    success: bool
    attempts: int
    findings: list[ReviewFinding]
    summary: str
    repo_path: str | None = None
    repo_url: str | None = None
    container_port: int | None = None


def _reset_app_dir(app_dir: Path) -> None:
    """Greenfield only: full wipe so each attempt starts from nothing."""
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)


def _reset_for_pickup(app_dir: Path) -> None:
    """Pickup retry: discard a failed attempt's uncommitted changes while
    keeping the existing app's committed history intact — a wipe would destroy
    the very app the attempt was supposed to modify."""
    subprocess.run(
        ["git", "checkout", "--", "."], cwd=app_dir, check=True, capture_output=True, text=True
    )
    subprocess.run(["git", "clean", "-fd"], cwd=app_dir, check=True, capture_output=True, text=True)


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
    subprocess.run(["git", "init", "-q"], cwd=app_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "-A"], cwd=app_dir, check=True, capture_output=True, text=True)
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
        capture_output=True,
        text=True,
    )


def _git_commit_change(app_dir: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=app_dir, check=True, capture_output=True, text=True)
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
            message,
        ],
        cwd=app_dir,
        check=True,
        capture_output=True,
        text=True,
    )


def _dockerize(app_dir: Path, slug: str, port: int | None = None) -> tuple[str, int]:
    client = get_docker_client()
    resolved_port = port if port is not None else allocate_port(client)
    build_and_run(client, app_dir, slug, resolved_port)
    return str(app_dir), resolved_port


def _no_repo_failure(session: Session, build_review_run: Run, app: App) -> BuildReviewView:
    """Legible error, not a crash: a seeded app (or one otherwise missing its
    repo on disk) has nothing for a pickup to modify."""
    finding = ReviewFinding(
        severity="high",
        category="missing_repo",
        description=(
            f"App '{app.slug}' has no repo on disk at {app.repo_path!r} to modify — "
            "pickup can't proceed against a seeded or otherwise unbuildable app."
        ),
    )
    build_review_run.outcome = "failed"
    build_review_run.review = {
        "attempts": 0,
        "findings": [finding.model_dump()],
        "summary": "No repo on disk for this app; nothing to modify.",
    }
    session.commit()
    return BuildReviewView(
        run_id=build_review_run.id,
        success=False,
        attempts=0,
        findings=[finding],
        summary="No repo on disk for this app; nothing to modify.",
    )


async def run_build_and_review(session: Session, plan_run: Run) -> BuildReviewView:
    settings = get_build_settings()
    plan = plan_run.plan["result"]

    target_app = session.get(App, plan_run.app_id) if plan_run.app_id else None
    is_pickup = target_app is not None

    if is_pickup:
        slug = target_app.slug
        app_dir = Path(target_app.repo_path)
    else:
        slug = slugify(plan["name"])
        app_dir = GENERATED_APPS_DIR / slug

    build_review_run = Run(kind="build_review", plan_run_id=plan_run.id, app_id=plan_run.app_id)
    session.add(build_review_run)
    session.commit()

    if is_pickup and not app_dir.is_dir():
        return _no_repo_failure(session, build_review_run, target_app)

    if is_pickup:
        # The repo is host-owned from its prior registration (chowned at the
        # end of that run), but git runs as root throughout this run — same
        # dubious-ownership wall as the greenfield case, just hit immediately
        # instead of only on git init/commit, since this directory didn't
        # start root-owned via mkdir the way a fresh build's does (observed
        # live). Chown back to root for the duration; back to the host user
        # at the end, same as greenfield.
        _chown_to_host_user(app_dir, 0, 0)

    all_findings: list[ReviewFinding] = []
    feedback: str | None = None

    for attempt in range(1, settings.max_build_review_attempts + 1):
        if is_pickup:
            if attempt > 1:
                _reset_for_pickup(app_dir)
        else:
            _reset_app_dir(app_dir)

        build_result = await run_build_turn(
            app_dir=app_dir, plan=plan, feedback=feedback, is_pickup=is_pickup
        )
        _record_cost(session, build_review_run, "build", build_result.model_usage)

        # Chowning to the host user mid-loop (for inspectability of a failed
        # attempt) is only safe for greenfield: the next attempt's
        # _reset_app_dir does rm -rf + mkdir, so it's root-owned again
        # regardless. Pickup's retry instead does `git checkout`/`clean`
        # against the *same* directory — chowning it to the host user here
        # would make that next git call hit the dubious-ownership wall all
        # over again (observed live). So pickup stays root-owned until one of
        # the return points below.

        static_findings = scan_statically(app_dir)
        # Only high-severity static-analysis findings block the pipeline —
        # bandit/ruff's own severity grading already distinguishes "seems
        # safe" (e.g. a literal shell command) from genuinely dangerous
        # patterns (e.g. untrusted input in a shell command). Medium/low
        # findings are quality signal for the human, not a build blocker.
        blocking_static_findings = [f for f in static_findings if f.severity == "high"]
        surfaced_static_findings = [f for f in static_findings if f.severity != "high"]

        gate_findings = (
            _check_required_files(app_dir) + scan_for_secrets(app_dir) + blocking_static_findings
        )
        if gate_findings:
            all_findings = gate_findings
            feedback = _feedback_text(gate_findings)
            if not is_pickup:
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
            if not is_pickup:
                _chown_to_host_user(app_dir, settings.host_uid, settings.host_gid)
            continue

        if review_turn.result.verdict != "pass":
            all_findings = review_turn.result.findings
            feedback = _feedback_text(all_findings)
            if not is_pickup:
                _chown_to_host_user(app_dir, settings.host_uid, settings.host_gid)
            continue

        try:
            # git runs as root (this container's user) against a still
            # root-owned directory — chowning to the host user has to wait
            # until after git is done, or git's own dubious-ownership check
            # refuses to operate on a repo it doesn't own (observed live).
            # The Gitea push goes here too, for the same reason: it's a git
            # operation against the same root-owned working tree.
            if is_pickup:
                _git_commit_change(app_dir, f"Add capability: {plan['name']}")
                repo_url = push_to_gitea(app_dir, slug, get_gitea_settings())
                repo_path, container_port = _dockerize(app_dir, slug, target_app.container_port)
            else:
                _git_init_and_commit(app_dir)
                repo_url = push_to_gitea(app_dir, slug, get_gitea_settings())
                repo_path, container_port = _dockerize(app_dir, slug)
        except Exception as exc:  # noqa: BLE001 - any docker/git/gitea failure is a retryable build failure
            detail = getattr(exc, "stderr", None) or str(exc)
            all_findings = [
                ReviewFinding(
                    severity="high",
                    category="build_failed",
                    description=f"git/gitea/docker step failed: {detail}",
                )
            ]
            feedback = _feedback_text(all_findings)
            continue
        finally:
            _chown_to_host_user(app_dir, settings.host_uid, settings.host_gid)

        final_findings = review_turn.result.findings + surfaced_static_findings

        build_review_run.outcome = "success"
        build_review_run.repo_path = repo_path
        build_review_run.repo_url = repo_url
        build_review_run.container_port = container_port
        build_review_run.review = {
            "attempts": attempt,
            "findings": [f.model_dump() for f in final_findings],
            "summary": review_turn.result.summary,
        }
        session.commit()
        return BuildReviewView(
            run_id=build_review_run.id,
            success=True,
            attempts=attempt,
            findings=final_findings,
            summary=review_turn.result.summary,
            repo_path=repo_path,
            repo_url=repo_url,
            container_port=container_port,
        )

    if is_pickup:
        _chown_to_host_user(app_dir, settings.host_uid, settings.host_gid)

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
