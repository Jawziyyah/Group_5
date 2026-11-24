import streamlit as st

import db
from analytics import numbered
from app_config import require_student
from ui_utils import esc

student = require_student()


def show_list():
    st.title("My dashboard")
    st.caption(f"Welcome, {student['name']}." + (f" ID: {student['student_ref']}" if student["student_ref"] else ""))
    if st.button("Take an assessment", type="primary"):
        st.switch_page("views/take.py")

    subs = db.list_student_submissions(student["id"])
    st.subheader("My assessments")
    if not subs:
        st.info("You haven't taken any assessments yet. Choose Take an assessment and enter the code from your teacher.")
        return
    for s in subs:
        with st.container(border=True):
            left, right = st.columns([4, 1])
            left.markdown(f"**{esc(s['title'])}**")
            when = s["submitted_at"].strftime("%d %b %Y, %H:%M")
            if s["released"]:
                note = f"Submitted {when} · Score: {s['got']}/{s['out_of']}"
                if s["pending"]:
                    note += f" ({s['pending']} answer(s) still being marked)"
                left.caption(note)
                if right.button("View", key=f"view_{s['id']}"):
                    st.session_state["viewing_submission"] = s["id"]
                    st.rerun()
            else:
                left.caption(f"Submitted {when} · Waiting for your teacher to release the results")


def show_detail(submission_id):
    res = db.get_student_result(student["id"], submission_id)
    if res is None:                       # not found, or not this student's submission
        st.session_state.pop("viewing_submission", None)
        st.rerun()
    if st.button("Back to my dashboard"):
        st.session_state.pop("viewing_submission", None)
        st.rerun()
    st.title(res["title"])
    if not res["released"]:
        st.info("Your results haven't been released yet. Please check back later.")
        return

    answers = {x["question_id"]: x for x in res["answers"]}
    questions = numbered(res["questions"])
    got = sum(x["awarded"] or 0 for x in res["answers"])
    out_of = sum(q["marks"] for q in questions)
    waiting = sum(1 for x in res["answers"] if x["awarded"] is None)
    st.metric("Your score", f"{got}/{out_of}")
    if waiting:
        st.caption(f"{waiting} answer(s) haven't been marked yet, so your score may still change.")

    for q in questions:
        x = answers[q["id"]]
        with st.container(border=True):
            st.markdown(f"**Q{q['number']}. {esc(q['text'])}**")
            st.markdown(f"Your answer: {esc(x['response']) if x['response'] else '_(no answer)_'}")
            if x["awarded"] is None:
                st.markdown("Marks: _not marked yet_")
            else:
                st.markdown(f"Marks: **{x['awarded']}/{q['marks']}**")
                st.markdown(f"Correct answer: {esc(q['answer'])}")
            if x["feedback"]:
                st.markdown(f"Teacher feedback: {esc(x['feedback'])}")
            if q["explanation"] and x["awarded"] is not None:
                st.caption(esc(q["explanation"]))


viewing = st.session_state.get("viewing_submission")
show_detail(viewing) if viewing else show_list()
