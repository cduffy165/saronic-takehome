"""Feeds planted-defect fixtures straight to the secrets gate and Review, without
going through Build. Costs real money (one live Review call). Run inside the
api container: `make eval-review`.
"""

import asyncio
import sys
from pathlib import Path

from factory.agents.review_session import run_review_turn
from factory.agents.secrets_scanner import scan_directory

FIXTURES_DIR = Path(__file__).parent / "review_fixtures"


def check_hardcoded_secret() -> tuple[bool, str]:
    """The planted AWS key must be caught by the deterministic gate — no model
    call needed, or wanted, for this one: it should never even reach Review."""
    findings = scan_directory(FIXTURES_DIR / "hardcoded_secret")
    if any(f.category == "secrets" for f in findings):
        return True, f"secrets gate caught {len(findings)} finding(s), as expected"
    return False, "secrets gate found nothing — planted AWS key was missed"


async def check_injection_risk() -> tuple[bool, str]:
    fixture_dir = FIXTURES_DIR / "injection_risk"
    gate_findings = scan_directory(fixture_dir)
    if gate_findings:
        return False, f"fixture should be clean of secrets, but gate found: {gate_findings}"

    turn = await run_review_turn(app_dir=fixture_dir)
    if turn.result is None:
        return False, "Review did not return a structured result"
    if turn.result.verdict != "fail":
        return False, f"expected verdict=fail, got {turn.result.verdict}"
    if not any(
        "inject" in f.description.lower() or "sql" in f.description.lower()
        for f in turn.result.findings
    ):
        return (
            False,
            f"verdict failed but no finding mentions injection/SQL: {turn.result.findings}",
        )
    return True, "Review correctly failed the app and flagged the injection risk"


async def main() -> None:
    results = []

    ok, detail = check_hardcoded_secret()
    results.append(("hardcoded_secret", ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] hardcoded_secret: {detail}")

    ok, detail = await check_injection_risk()
    results.append(("injection_risk", ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] injection_risk: {detail}")

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
