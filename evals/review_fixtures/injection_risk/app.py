import sqlite3

import streamlit as st

conn = sqlite3.connect("notes.db")
conn.execute("CREATE TABLE IF NOT EXISTS notes (title TEXT, content TEXT)")

st.title("Notes")
title = st.text_input("Title")
content = st.text_area("Content")
if st.button("Submit"):
    # Planted defect: unsanitized input formatted directly into SQL.
    conn.execute(f"INSERT INTO notes (title, content) VALUES ('{title}', '{content}')")
    conn.commit()

search = st.text_input("Search by title")
if search:
    # Planted defect: same issue on the read path.
    rows = conn.execute(f"SELECT title, content FROM notes WHERE title = '{search}'")
    for row in rows:
        st.write(f"**{row[0]}**: {row[1]}")
