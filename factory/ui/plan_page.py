"""Request intake: the interactive Plan session chat, with the Gate 1 and Gate 2
approval buttons."""

import os

import httpx
import streamlit as st

from factory.registry.identity import display_name

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

_ROUTE_REASONS = {
    "overlaps_existing_app": "an app that already does this exists",
    "scope_exceeds_blueprint": "this is bigger than what gets built automatically",
    "no_fitting_blueprint": "this doesn't fit the one app pattern this factory builds",
}


def render(access_token: str) -> None:
    st.subheader("📝 Request an app")
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    if "plan_run_id" not in st.session_state:
        st.session_state.plan_run_id = None
        st.session_state.plan_transcript = []
        st.session_state.plan_done = False
        st.session_state.plan_outcome = None
        st.session_state.build_review_result = None
        st.session_state.registered_app = None

    for turn in st.session_state.plan_transcript:
        with st.chat_message(turn["role"]):
            st.write(turn["content"])

    if st.session_state.plan_done:
        _render_outcome(st.session_state.plan_outcome, st.session_state.plan_run_id, auth_headers)
        if st.button("Start a new request"):
            st.session_state.plan_run_id = None
            st.session_state.plan_transcript = []
            st.session_state.plan_done = False
            st.session_state.plan_outcome = None
            st.session_state.build_review_result = None
            st.session_state.registered_app = None
            st.rerun()
        return

    message = st.chat_input("Describe the app you need...")
    if not message:
        return

    st.session_state.plan_transcript.append({"role": "user", "content": message})
    with httpx.Client(base_url=API_BASE_URL, timeout=120.0, headers=auth_headers) as client:
        if st.session_state.plan_run_id is None:
            response = client.post("/plans", json={"message": message})
        else:
            response = client.post(
                f"/plans/{st.session_state.plan_run_id}/messages", json={"message": message}
            )
    response.raise_for_status()
    turn = response.json()

    st.session_state.plan_run_id = turn["run_id"]
    st.session_state.plan_transcript.append({"role": "assistant", "content": turn["message"]})
    st.session_state.plan_done = turn["done"]
    st.session_state.plan_outcome = turn["outcome"]
    st.rerun()


def _render_outcome(outcome: dict | None, run_id: str, auth_headers: dict[str, str]) -> None:
    if outcome is None:
        return

    kind = outcome["outcome"]
    if kind == "proceed":
        st.success(
            f"**{outcome['name']}** — ready to build (complexity score {outcome['complexity_score']})."
        )
        st.write(outcome["purpose"])
        st.write("Capabilities:")
        for cap in outcome["capabilities"]:
            st.write(f"- **{cap['slug']}** — {cap['description']}")

        if st.session_state.build_review_result is None:
            if st.button("Approve — proceed to Build", type="primary"):
                with (
                    st.spinner("Building and reviewing — this can take a minute..."),
                    httpx.Client(
                        base_url=API_BASE_URL, timeout=300.0, headers=auth_headers
                    ) as client,
                ):
                    approve_response = client.post(f"/plans/{run_id}/approve")
                if approve_response.status_code == 200:
                    st.session_state.build_review_result = approve_response.json()
                    st.rerun()
                else:
                    st.error(approve_response.json().get("detail", "Approval failed."))
        else:
            _render_build_review_result(st.session_state.build_review_result, auth_headers)

    elif kind == "route_to_human":
        st.warning(outcome["message"])
        reason = _ROUTE_REASONS.get(outcome["reason"], outcome["reason"])
        st.caption(f"Talk to **{display_name(outcome['owner_sub'])}** — {reason}.")
        if outcome.get("owner_note"):
            st.caption(outcome["owner_note"])

    elif kind == "feature_request":
        st.info(
            f"Filed as a feature request against **{outcome['target_app_slug']}**. "
            "Its owner will see this in their inbox."
        )

    elif kind == "incomplete":
        st.error(
            f"Ran out of planning turns ({outcome['turns_used']}) before reaching a decision. "
            f"Still needed: {outcome['still_needed']}"
        )


def _render_build_review_result(result: dict, auth_headers: dict[str, str]) -> None:
    if result["success"]:
        st.success(f"Built and reviewed in {result['attempts']} attempt(s). {result['summary']}")
        st.link_button("Open the running app", f"http://localhost:{result['container_port']}")
        st.caption(f"Source: {result['repo_url']}")

        if st.session_state.registered_app is None:
            if st.button("Approve — Register", type="primary"):
                with httpx.Client(
                    base_url=API_BASE_URL, timeout=30.0, headers=auth_headers
                ) as client:
                    register_response = client.post(f"/builds/{result['run_id']}/approve")
                if register_response.status_code == 200:
                    st.session_state.registered_app = register_response.json()
                    st.rerun()
                else:
                    st.error(register_response.json().get("detail", "Registration failed."))
        else:
            registered = st.session_state.registered_app
            st.success(f"Registered as **{registered['slug']}** in the registry.")
    else:
        st.error(f"Failed after {result['attempts']} attempt(s): {result['summary']}")

    if result["findings"]:
        severity_colors = {"high": "red", "medium": "orange", "low": "gray"}
        st.markdown("**Findings**")
        for finding in result["findings"]:
            color = severity_colors.get(finding["severity"], "gray")
            category = finding["category"].replace("_", " ")
            st.markdown(
                f":{color}-badge[{finding['severity']}] {category} — {finding['description']}"
            )
