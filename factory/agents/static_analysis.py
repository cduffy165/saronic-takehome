"""Deterministic static analysis on a generated app, run before Review sees it.

Two tools, not one, deliberately: bandit is purpose-built for Python security
issues with a stable, well-documented rule set; ruff's flake8-bandit-derived
"S" rules cover much of the same ground but run through the linter already in
this project's toolchain, so enabling them costs nothing extra to depend on.
They overlap more than they differ, but each has caught things the other
missed in spot checks, and both are cheap to run against a handful of files.

Review's own judgment (an LLM reading the file tree) is still what grades
overall quality and whether the app does what it claims — these tools only
catch the specific, nameable Python security antipatterns they're built for.
"""

import json
import subprocess
from pathlib import Path

from factory.agents.build_review_schema import ReviewFinding

_BANDIT_SEVERITY = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}


def _run_bandit(root: Path) -> list[ReviewFinding]:
    result = subprocess.run(
        ["bandit", "-r", "-f", "json", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    if not result.stdout:
        return []
    payload = json.loads(result.stdout)
    findings = []
    for issue in payload.get("results", []):
        rel = Path(issue["filename"]).relative_to(root)
        findings.append(
            ReviewFinding(
                severity=_BANDIT_SEVERITY.get(issue["issue_severity"], "low"),
                category="static_analysis",
                description=(
                    f"{rel}:{issue['line_number']}: [bandit {issue['test_id']}] "
                    f"{issue['issue_text']}"
                ),
            )
        )
    return findings


def _run_ruff_security(root: Path) -> list[ReviewFinding]:
    result = subprocess.run(
        ["ruff", "check", "--select", "S", "--no-cache", "--output-format", "json", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    if not result.stdout:
        return []
    issues = json.loads(result.stdout)
    findings = []
    for issue in issues:
        rel = Path(issue["filename"]).relative_to(root)
        findings.append(
            ReviewFinding(
                severity="medium",
                category="static_analysis",
                description=(
                    f"{rel}:{issue['location']['row']}: [ruff {issue['code']}] {issue['message']}"
                ),
            )
        )
    return findings


def scan_directory(root: Path) -> list[ReviewFinding]:
    return _run_bandit(root) + _run_ruff_security(root)
