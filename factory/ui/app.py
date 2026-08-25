"""Streamlit entrypoint for the app factory's UI."""

import streamlit as st

from factory.ui import registry_page

st.set_page_config(page_title="App Factory", layout="wide")
st.title("App Factory")
st.caption("Request intake, plan chat, and approval gates land in later milestones.")

registry_page.render()
