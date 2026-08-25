"""Read-only registry browser: what apps exist, what they do, what they cost, who owns them."""

from collections.abc import Sequence

import streamlit as st

from factory.registry.db import get_session_factory
from factory.registry.identity import display_name
from factory.registry.models import App
from factory.registry.queries import find_apps_owned_by, list_apps

_STATUS_COLORS = {"active": "green", "retired": "gray"}
_ROLE_COLORS = {"business": "violet", "technical": "blue"}


def render(current_user_sub: str | None = None) -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        if current_user_sub is not None:
            st.subheader("My apps")
            _render_apps(find_apps_owned_by(session, current_user_sub), empty_message="none yet")

        st.subheader("Everything registered")
        _render_apps(list_apps(session), empty_message="Nothing has been registered yet.")


def _render_apps(apps: Sequence[App], *, empty_message: str) -> None:
    if not apps:
        st.info(empty_message, icon="📭")
        return

    for app in apps:
        with st.expander(f"**{app.name}**"):
            st.badge(app.status, color=_STATUS_COLORS.get(app.status, "gray"))
            st.write(app.purpose)
            st.caption(f"Blueprint: {app.blueprint_id}  ·  Complexity: {app.complexity_score}/5")

            if app.capabilities:
                st.markdown("**Capabilities**")
                for capability in app.capabilities:
                    st.markdown(f"- **{capability.slug}** — {capability.description}")

            st.markdown("**Owners**")
            owner_badges = "  ".join(
                f":{_ROLE_COLORS.get(owner.role, 'gray')}-badge[{display_name(owner.keycloak_sub)} · {owner.role}]"
                for owner in app.owners
            )
            st.markdown(owner_badges)

            total_cost = sum(event.usd for run in app.runs for event in run.cost_events)
            cost_col, links_col = st.columns(2)
            with cost_col:
                st.metric(
                    "Cost to date", f"${total_cost:,.4f}", help=f"Across {len(app.runs)} run(s)"
                )
            with links_col:
                if app.repo_url:
                    st.link_button("View source", app.repo_url, width="stretch")
                if app.container_port:
                    st.link_button(
                        "Open app", f"http://localhost:{app.container_port}", width="stretch"
                    )
