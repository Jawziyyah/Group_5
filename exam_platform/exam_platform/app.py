"""Entry point. Deploy this file as the main file."""
import streamlit as st

import db
from app_config import get_secret

st.set_page_config(page_title="Exam Platform", page_icon="📝", layout="centered")
db.init(get_secret("DATABASE_URL"))

teacher = st.session_state.get("teacher")

with st.sidebar:
    if teacher:
        st.caption(f"Signed in as **{teacher['name']}**")
        if not get_secret("GEMINI_API_KEY"):
            st.text_input("Gemini API key", type="password", key="user_api_key",
                          help="Needed to generate questions and mark theory answers. Get one at aistudio.google.com/apikey.")
        if not get_secret("DATABASE_URL"):
            st.caption("Data is saved in a local file. On Streamlit Cloud that is wiped when the app restarts - "
                       "set DATABASE_URL to keep it.")
        if st.button("Log out"):
            for key in ("teacher", "draft", "editing_id", "selected_assessment", "just_published", "flash"):
                st.session_state.pop(key, None)
            st.rerun()

if teacher:
    pages = [
        st.Page("views/assessments.py", title="My assessments", icon="📋", url_path="assessments", default=True),
        st.Page("views/create.py", title="Create assessment", icon="➕", url_path="create"),
        st.Page("views/take.py", title="Take an assessment", icon="✏️", url_path="take"),
    ]
else:
    pages = [
        st.Page("views/take.py", title="Take an assessment", icon="✏️", url_path="take", default=True),
        st.Page("views/login.py", title="Teacher login", icon="🔑", url_path="login"),
    ]

st.navigation(pages).run()
