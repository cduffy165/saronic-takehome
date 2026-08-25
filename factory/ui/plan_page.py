"""Request intake: the interactive Plan session chat, with the Gate 1 approval button."""

import os

import httpx
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


def render(current_user_sub: str) -> None:
    st.header("Request an App")

    if "plan_run_id" not in st.session_state:
        st.session_state.plan_run_id = None
        st.session_state.plan_transcript = []
        st.session_state.plan_done = False
        st.session_state.plan_outcome = None

    for turn in st.session_state.plan_transcript:
        with st.chat_message(turn["role"]):
            st.write(turn["content"])

    if st.session_state.plan_done:
        _render_outcome(st.session_state.plan_outcome, st.session_state.plan_run_id)
        if st.button("Start a new request"):
            st.session_state.plan_run_id = None
            st.session_state.plan_transcript = []
            st.session_state.plan_done = False
            st.session_state.plan_outcome = None
            st.rerun()
        return

    message = st.chat_input("Describe the app you need...")
    if not message:
        return

    st.session_state.plan_transcript.append({"role": "user", "content": message})
    with httpx.Client(base_url=API_BASE_URL, timeout=120.0) as client:
        if st.session_state.plan_run_id is None:
            response = client.post(
                "/plans", json={"requester_sub": current_user_sub, "message": message}
            )
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


def _render_outcome(outcome: dict | None, run_id: str) -> None:
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
        if st.button("Approve — proceed to Build"):
            with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
                approve_response = client.post(f"/plans/{run_id}/approve")
            if approve_response.status_code == 200:
                st.success("Approved. Build isn't implemented yet (M5) — this plan is queued.")
            else:
                st.error(approve_response.json().get("detail", "Approval failed."))

    elif kind == "route_to_human":
        st.warning(outcome["message"])
        st.caption(f"Owner: {outcome['owner_note']} · reason: {outcome['reason']}")

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
