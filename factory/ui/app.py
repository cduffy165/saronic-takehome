"""Streamlit entrypoint for the app factory's UI."""

import streamlit as st

from factory.ui import registry_page

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

st.caption("Request intake, plan chat, and approval gates land in later milestones.")

registry_page.render(current_user_sub=st.user.sub)
