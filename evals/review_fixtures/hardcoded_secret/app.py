import sqlite3

import streamlit as st

# Planted defect: a hardcoded AWS credential. This must be caught by the
# deterministic secrets gate (gitleaks) before Review ever sees the tree.
AWS_ACCESS_KEY = "AKIAABCDEFGHIJKLMNOP"

conn = sqlite3.connect("notes.db")
conn.execute("CREATE TABLE IF NOT EXISTS notes (title TEXT, content TEXT)")

st.title("Notes")
title = st.text_input("Title")
content = st.text_area("Content")
if st.button("Submit"):
    conn.execute("INSERT INTO notes (title, content) VALUES (?, ?)", (title, content))
    conn.commit()

for row in conn.execute("SELECT title, content FROM notes"):
    st.write(f"**{row[0]}**: {row[1]}")
