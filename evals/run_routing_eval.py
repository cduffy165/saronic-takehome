"""Drives the routing eval fixtures through the real /plans API using scripted
requesters. Calls the live Claude Agent SDK via the api service — costs real
money. Run inside the stack: `make eval-routing` (which execs into the api
container; this must not be run against a host-side Anthropic key per the
CLAUDE.md isolation rule).
"""

import os
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from evals.keycloak_auth import get_access_token
from evals.scripted_requester import ScriptedRequester

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
CASES_PATH = Path(__file__).parent / "routing_cases.yaml"
MAX_TURNS = 8


def run_case(client: httpx.Client, case: dict[str, Any]) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {get_access_token(case['requester_sub'])}"}

    response = client.post("/plans", json={"message": case["opening_message"]}, headers=headers)
    response.raise_for_status()
    turn = response.json()

    requester = ScriptedRequester(
        answers=case.get("answers", {}), fallback_reply=case["fallback_reply"]
    )
    while not turn["done"] and turn["turns_used"] < MAX_TURNS:
        reply = requester.reply_to(turn["message"])
        response = client.post(
            f"/plans/{turn['run_id']}/messages", json={"message": reply}, headers=headers
        )
        response.raise_for_status()
        turn = response.json()

    return turn


def check_case(case: dict[str, Any], turn: dict[str, Any]) -> tuple[bool, str]:
    outcome = turn.get("outcome") or {}
    actual_kind = outcome.get("outcome")
    expected_kind = case["expected_outcome"]

    if actual_kind != expected_kind:
        return False, f"expected outcome={expected_kind}, got {actual_kind}"

    if "expected_owner_sub" in case and outcome.get("owner_sub") != case["expected_owner_sub"]:
        return (
            False,
            f"expected owner_sub={case['expected_owner_sub']}, got {outcome.get('owner_sub')}",
        )

    if (
        "expected_target_app_slug" in case
        and outcome.get("target_app_slug") != case["expected_target_app_slug"]
    ):
        return (
            False,
            f"expected target_app_slug={case['expected_target_app_slug']}, "
            f"got {outcome.get('target_app_slug')}",
        )

    return True, "ok"


def main() -> None:
    cases = yaml.safe_load(CASES_PATH.read_text())["cases"]
    results = []

    with httpx.Client(base_url=API_BASE_URL, timeout=120.0) as client:
        for case in cases:
            turn = run_case(client, case)
            passed, detail = check_case(case, turn)
            results.append((case["id"], passed, detail))
            status = "PASS" if passed else "FAIL"
            print(f"[{status}] {case['id']}: {detail}")

    passed_count = sum(1 for _, passed, _ in results if passed)
    print(f"\n{passed_count}/{len(results)} passed")
    sys.exit(0 if passed_count == len(results) else 1)


if __name__ == "__main__":
    main()
