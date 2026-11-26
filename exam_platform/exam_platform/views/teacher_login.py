import streamlit as st

import auth
import db
from app_config import get_secret

st.title("Teacher sign in")
st.caption("For teachers only. Students: use the Student sign in page.")

teacher = st.session_state.get("teacher")
if teacher:
    st.success(f"You are signed in as {teacher['name']} ({teacher['email']}).")
    st.stop()

invite_required = get_secret("TEACHER_INVITE_CODE")
login_tab, register_tab = st.tabs(["Log in", "Create account"])

with login_tab:
    with st.form("teacher_login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")
    if submitted:
        found = db.get_teacher_by_email(email) if email.strip() else None
        if found and auth.verify_password(password, found["password_hash"]):
            st.session_state.pop("student", None)
            st.session_state["teacher"] = dict(id=found["id"], name=found["name"], email=found["email"])
            st.rerun()
        else:
            st.error("Incorrect email or password.")

with register_tab:
    with st.form("teacher_register_form"):
        name = st.text_input("Your name")
        new_email = st.text_input("Email", key="reg_email")
        new_password = st.text_input("Password", type="password", key="reg_password",
                                     help="At least 8 characters.")
        confirm = st.text_input("Confirm password", type="password")
        invite = st.text_input("Invite code") if invite_required else ""
        created = st.form_submit_button("Create account", type="primary")
    if created:
        problem = None
        if not name.strip():
            problem = "Please enter your name."
        elif not auth.valid_email(new_email):
            problem = "Please enter a valid email address."
        elif auth.password_problem(new_password):
            problem = auth.password_problem(new_password)
        elif new_password != confirm:
            problem = "The passwords don't match."
        elif invite_required and invite.strip() != str(invite_required):
            problem = "That invite code isn't right."
        if problem:
            st.error(problem)
        else:
            try:
                t = db.create_teacher(new_email, name, auth.hash_password(new_password))
            except db.DuplicateError as e:
                st.error(str(e))
            else:
                st.session_state.pop("student", None)
                st.session_state["teacher"] = dict(id=t["id"], name=t["name"], email=t["email"])
                st.rerun()
