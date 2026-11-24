import streamlit as st

import auth
import db

st.title("Student sign in")

student = st.session_state.get("student")
if student:
    st.success(f"You are signed in as {student['name']} ({student['email']}).")
    st.stop()

st.caption("Sign in to take assessments and see your results. First time here? Choose Create account. "
           "Teachers: use the Teacher sign in page.")
login_tab, register_tab = st.tabs(["Log in", "Create account"])

with login_tab:
    with st.form("student_login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")
    if submitted:
        found = db.get_student_by_email(email) if email.strip() else None
        if found and auth.verify_password(password, found["password_hash"]):
            st.session_state.pop("teacher", None)
            st.session_state["student"] = dict(id=found["id"], name=found["name"], email=found["email"],
                                               student_ref=found["student_ref"])
            st.rerun()
        else:
            st.error("Incorrect email or password.")

with register_tab:
    with st.form("student_register_form"):
        name = st.text_input("Full name", help="Use the name your teacher knows you by.")
        ref = st.text_input("School or student ID (optional)")
        new_email = st.text_input("Email", key="stu_reg_email")
        new_password = st.text_input("Password", type="password", key="stu_reg_password",
                                     help="At least 8 characters.")
        confirm = st.text_input("Confirm password", type="password", key="stu_reg_confirm")
        created = st.form_submit_button("Create account", type="primary")
    if created:
        problem = None
        if len(name.strip()) < 2:
            problem = "Please enter your full name."
        elif not auth.valid_email(new_email):
            problem = "Please enter a valid email address."
        elif auth.password_problem(new_password):
            problem = auth.password_problem(new_password)
        elif new_password != confirm:
            problem = "The passwords don't match."
        if problem:
            st.error(problem)
        else:
            try:
                created_student = db.create_student(new_email, name, ref, auth.hash_password(new_password))
            except db.DuplicateError as e:
                st.error(str(e))
            else:
                st.session_state.pop("teacher", None)
                st.session_state["student"] = dict(id=created_student["id"], name=created_student["name"],
                                                   email=created_student["email"],
                                                   student_ref=created_student["student_ref"])
                st.rerun()
