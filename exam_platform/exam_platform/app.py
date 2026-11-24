"""Entry point. Deploy this file as the main file. Teachers and students each get their own set of pages."""
import streamlit as st

import db
from app_config import get_secret

st.set_page_config(page_title="Exam Platform", page_icon="📝", layout="centered")
db.init(get_secret("DATABASE_URL"))

teacher = st.session_state.get("teacher")
student = st.session_state.get("student")

with st.sidebar:
    who = teacher or student
    if who:
        st.caption(f"Signed in as **{who['name']}** ({'teacher' if teacher else 'student'})")
    if teacher:
        if not get_secret("GEMINI_API_KEY"):
            st.text_input("Gemini API key", type="password", key="user_api_key",
                          help="Needed to generate questions and mark theory answers. Get one at aistudio.google.com/apikey.")
        if not get_secret("DATABASE_URL"):
            st.caption("Data is saved in a local file. On Streamlit Cloud that is wiped when the app restarts - "
                       "set DATABASE_URL to keep it.")
    if who and st.button("Log out"):
        for key in ("teacher", "student", "draft", "editing_id", "selected_assessment", "just_published", "flash",
                    "take", "take_done", "viewing_submission"):
            st.session_state.pop(key, None)
        st.rerun()

if teacher:        # teacher portal
    pages = [
        st.Page("views/assessments.py", title="My assessments", icon="📋", url_path="assessments", default=True),
        st.Page("views/create.py", title="Create assessment", icon="➕", url_path="create"),
    ]
elif student:      # student portal
    pages = [
        st.Page("views/student_home.py", title="My dashboard", icon="🏠", url_path="dashboard", default=True),
        st.Page("views/take.py", title="Take an assessment", icon="✏️", url_path="take"),
    ]
else:              # signed out: choose a portal
    pages = [
        st.Page("views/student_login.py", title="Student sign in", icon="🎓", url_path="student", default=True),
        st.Page("views/teacher_login.py", title="Teacher sign in", icon="🔑", url_path="teacher"),
    ]

st.navigation(pages).run()
