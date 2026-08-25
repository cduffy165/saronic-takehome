"""Streamlit entrypoint for the app factory's UI."""

import streamlit as st

from factory.ui import feature_requests_page, plan_page, registry_page

st.set_page_config(page_title="App Factory", page_icon="🏭", layout="wide")
st.title("🏭 App Factory")
st.caption("Describe the internal app you need — plain language in, a working app out.")

if not st.user.is_logged_in:
    st.info("Sign in with your Keycloak identity to continue.")
    st.button("Log in", on_click=st.login, type="primary")
    st.stop()

PAGE_ICONS = {"Request an App": "📝", "Registry": "📚", "Feature Requests": "📬"}

with st.sidebar:
    display_name = st.user.get("name") or st.user.get("preferred_username", "unknown")
    st.markdown(f"**{display_name}**")
    st.button("Log out", on_click=st.logout, width="stretch")
    st.divider()
    # key="page" binds the radio to session_state.page — feature_requests_page
    # sets it directly (then reruns) to hand off into the Plan chat after pickup.
    # format_func only changes the label shown, not the underlying value that
    # coupling depends on.
    page = st.radio(
        "View",
        list(PAGE_ICONS),
        key="page",
        label_visibility="collapsed",
        format_func=lambda name: f"{PAGE_ICONS[name]}  {name}",
    )

if page == "Request an App":
    plan_page.render(access_token=st.user.tokens.access)
elif page == "Registry":
    registry_page.render(current_user_sub=st.user.sub)
else:
    feature_requests_page.render(access_token=st.user.tokens.access)
