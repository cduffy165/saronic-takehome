"""Deterministic secrets scan — a hard gate independent of Review's own judgment.

Generated apps may only use placeholder credentials; the factory's own API key
must never enter generated code. This runs regardless of what the Review agent
concludes, so a model miss never becomes a silent pass.

Two layers, because they catch different things:
- gitleaks (subprocess, broad maintained pattern/entropy library) for
  general-purpose credential shapes — AWS keys, private key blocks, generic
  keyword-adjacent high-entropy secrets.
- A bespoke check for the literal value of *our own* live secrets. No
  general-purpose scanner can know those are ours — and gitleaks's generic
  pattern, tested directly, does not even match Anthropic's own `sk-ant-...`
  key format, so this check is not redundant with the scanner above.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from factory.agents.build_review_schema import ReviewFinding

_ENV_VARS_TO_CHECK = ("ANTHROPIC_API_KEY", "DATABASE_URL")
_SKIP_DIRS = {".git", "__pycache__", ".venv"}


def _run_gitleaks(root: Path) -> list[ReviewFinding]:
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "report.json"
        subprocess.run(
            [
                "gitleaks",
                "detect",
                "--source",
                str(root),
                "--no-git",
                "--report-format",
                "json",
                "--report-path",
                str(report_path),
                "--exit-code",
                "0",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        leaks = json.loads(report_path.read_text()) if report_path.exists() else []

    findings = []
    for leak in leaks:
        file_path = Path(leak["File"])
        rel = file_path.relative_to(root) if file_path.is_absolute() else file_path
        findings.append(
            ReviewFinding(
                severity="high",
                category="secrets",
                description=f"{rel}:{leak['StartLine']}: {leak['RuleID']} — {leak['Description']}",
            )
        )
    return findings


def _literal_factory_secret_findings(root: Path) -> list[ReviewFinding]:
    factory_secret_values = [
        v for name in _ENV_VARS_TO_CHECK if (v := os.environ.get(name)) and len(v) >= 8
    ]
    if not factory_secret_values:
        return []

    findings = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(root)
        for secret_value in factory_secret_values:
            if secret_value in text:
                findings.append(
                    ReviewFinding(
                        severity="high",
                        category="secrets",
                        description=(
                            f"{rel}: contains a literal value from the factory's own "
                            "environment — the factory's credentials must never enter "
                            "generated code."
                        ),
                    )
                )
    return findings


def scan_directory(root: Path) -> list[ReviewFinding]:
    return _run_gitleaks(root) + _literal_factory_secret_findings(root)
