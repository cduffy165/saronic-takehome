"""Read-only registry browser: what apps exist, what they do, what they cost, who owns them."""

from collections.abc import Sequence

import streamlit as st

from factory.registry.db import get_session_factory
from factory.registry.models import App
from factory.registry.queries import find_apps_owned_by, list_apps


def render(current_user_sub: str | None = None) -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        if current_user_sub is not None:
            st.header("My Apps")
            _render_apps(find_apps_owned_by(session, current_user_sub))

        st.header("Registry")
        _render_apps(list_apps(session))


def _render_apps(apps: Sequence[App]) -> None:
    if not apps:
        st.info("No apps here yet.")
        return

    for app in apps:
        with st.expander(f"{app.name}  ·  {app.status}"):
            st.write(app.purpose)
            st.caption(f"blueprint: {app.blueprint_id} · complexity score: {app.complexity_score}")
            if app.repo_url:
                st.write(f"Repo: {app.repo_url}")
            if app.container_port:
                st.write(f"Running at: http://localhost:{app.container_port}")

            st.subheader("Capabilities")
            for capability in app.capabilities:
                st.write(f"- **{capability.slug}** — {capability.description}")

            st.subheader("Owners")
            for owner in app.owners:
                st.write(f"- {owner.keycloak_sub} ({owner.role})")

            total_cost = sum(event.usd for run in app.runs for event in run.cost_events)
            st.subheader("Cost")
            st.write(f"${total_cost:,.4f} accumulated across {len(app.runs)} run(s)")
