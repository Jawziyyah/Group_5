import os

import streamlit as st


def get_secret(name: str):
    """Streamlit secret first, then environment variable."""
    try:
        value = st.secrets[name]
        if value:
            return value
    except Exception:
        pass
    return os.environ.get(name)


def get_api_key():
    """Server key from secrets, or the key a teacher typed into the sidebar."""
    return get_secret("GEMINI_API_KEY") or st.session_state.get("user_api_key") or None


def require_teacher() -> dict:
    teacher = st.session_state.get("teacher")
    if not teacher:
        st.warning("Please log in on the Teacher login page first.")
        st.stop()
    return teacher


def require_student() -> dict:
    student = st.session_state.get("student")
    if not student:
        st.warning("Please sign in on the Student sign in page first.")
        st.stop()
    return student
