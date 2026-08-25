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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from factory.agents.build_review_schema import ReviewFinding

_BANDIT_SEVERITY = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}

_BANDIT_CMD = ["bandit", "-r", "-f", "json"]
_RUFF_CMD = ["ruff", "check", "--select", "S", "--no-cache", "--output-format", "json"]


def _run_tool(cmd: list[str], root: Path) -> str:
    result = subprocess.run([*cmd, str(root)], capture_output=True, text=True, check=False)
    return result.stdout


def _bandit_findings(root: Path, stdout: str) -> list[ReviewFinding]:
    if not stdout:
        return []
    findings = []
    for issue in json.loads(stdout).get("results", []):
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


def _ruff_findings(root: Path, stdout: str) -> list[ReviewFinding]:
    if not stdout:
        return []
    findings = []
    for issue in json.loads(stdout):
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
    # Two independent subprocess calls with nothing to share — run concurrently
    # rather than paying bandit's and ruff's process-spawn cost back to back.
    tools: list[tuple[list[str], Callable[[Path, str], list[ReviewFinding]]]] = [
        (_BANDIT_CMD, _bandit_findings),
        (_RUFF_CMD, _ruff_findings),
    ]
    with ThreadPoolExecutor(max_workers=len(tools)) as pool:
        outputs = list(pool.map(lambda t: _run_tool(t[0], root), tools))
    return [
        finding
        for (_, parse), stdout in zip(tools, outputs, strict=True)
        for finding in parse(root, stdout)
    ]
