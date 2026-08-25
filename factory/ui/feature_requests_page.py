"""Feature request inbox: requests filed against apps the current user owns.

Picking one up hands off into the same Plan chat (factory/ui/plan_page.py) —
pre-seeded with the request's description — by writing into the same
session_state keys and switching the sidebar to that view.
"""

import os

import httpx
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


def render(access_token: str) -> None:
    st.header("Feature Requests")
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    with httpx.Client(base_url=API_BASE_URL, timeout=30.0, headers=auth_headers) as client:
        response = client.get("/feature-requests")
    response.raise_for_status()
    requests = response.json()

    if not requests:
        st.info("No open feature requests against apps you own.")
        return

    for fr in requests:
        with st.expander(f"{fr['app_slug']} — {fr['description'][:60]}"):
            st.write(fr["description"])
            st.caption(f"Requested by {fr['requester_sub']} · status: {fr['status']}")
            if st.button("Pick up", key=f"pickup-{fr['id']}"):
                _pick_up(fr, auth_headers)


def _pick_up(fr: dict, auth_headers: dict[str, str]) -> None:
    with (
        st.spinner("Starting plan session..."),
        httpx.Client(base_url=API_BASE_URL, timeout=60.0, headers=auth_headers) as client,
    ):
        pickup_response = client.post(f"/feature-requests/{fr['id']}/pickup")

    if pickup_response.status_code != 200:
        st.error(pickup_response.json().get("detail", "Pickup failed."))
        return

    turn = pickup_response.json()
    st.session_state.plan_run_id = turn["run_id"]
    st.session_state.plan_transcript = [
        {"role": "user", "content": fr["description"]},
        {"role": "assistant", "content": turn["message"]},
    ]
    st.session_state.plan_done = turn["done"]
    st.session_state.plan_outcome = turn["outcome"]
    st.session_state.build_review_result = None
    st.session_state.registered_app = None
    st.session_state.page = "Request an App"
    st.rerun()
