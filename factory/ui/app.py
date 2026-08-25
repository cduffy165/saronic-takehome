"""Streamlit entrypoint for the app factory's UI."""

import streamlit as st

from factory.ui import feature_requests_page, plan_page, registry_page

st.set_page_config(page_title="App Factory", layout="wide")
st.title("App Factory")

if not st.user.is_logged_in:
    st.caption("Sign in with your Keycloak identity to continue.")
    st.button("Log in", on_click=st.login)
    st.stop()

with st.sidebar:
    st.write(
        f"Signed in as **{st.user.get('preferred_username', st.user.get('name', 'unknown'))}**"
    )
    st.button("Log out", on_click=st.logout)
    # key="page" binds the radio to session_state.page — feature_requests_page
    # sets it directly (then reruns) to hand off into the Plan chat after pickup.
    page = st.radio("View", ["Request an App", "Registry", "Feature Requests"], key="page")

if page == "Request an App":
    plan_page.render(access_token=st.user.tokens.access)
elif page == "Registry":
    registry_page.render(current_user_sub=st.user.sub)
else:
    feature_requests_page.render(access_token=st.user.tokens.access)
