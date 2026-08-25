"""Read-only registry browser: what apps exist, what they do, what they cost, who owns them."""

import streamlit as st

from factory.registry.db import get_session_factory
from factory.registry.queries import list_apps


def render() -> None:
    st.header("Registry")

    session_factory = get_session_factory()
    with session_factory() as session:
        apps = list_apps(session)

        if not apps:
            st.info("No apps registered yet.")
            return

        for app in apps:
            with st.expander(f"{app.name}  ·  {app.status}"):
                st.write(app.purpose)
                st.caption(
                    f"blueprint: {app.blueprint_id} · complexity score: {app.complexity_score}"
                )

                st.subheader("Capabilities")
                for capability in app.capabilities:
                    st.write(f"- **{capability.slug}** — {capability.description}")

                st.subheader("Owners")
                for owner in app.owners:
                    st.write(f"- {owner.keycloak_sub} ({owner.role})")

                total_cost = sum(event.usd for run in app.runs for event in run.cost_events)
                st.subheader("Cost")
                st.write(f"${total_cost:,.4f} accumulated across {len(app.runs)} run(s)")
