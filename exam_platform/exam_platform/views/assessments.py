import pandas as pd
import streamlit as st

import db
from app_config import get_api_key, require_teacher
from grading import ai_mark_theory
from quiz_engine import make_client
from ui_utils import esc

teacher = require_teacher()
STATUS = {"draft": "Draft", "published": "Open", "closed": "Closed"}


def open_editor(assessment_id=None):
    st.session_state.pop("draft", None)
    st.session_state["editing_id"] = assessment_id
    st.switch_page("views/create.py")


# ------------------------------------------------------------------ list
def show_list():
    st.title("My assessments")
    if st.button("New assessment", type="primary"):
        open_editor()
    items = db.list_assessments(teacher["id"])
    if not items:
        st.info("You haven't created any assessments yet. Click New assessment to start.")
        return
    for a in items:
        with st.container(border=True):
            left, right = st.columns([4, 1])
            left.markdown(f"**{esc(a['title'])}**")
            details = f"{STATUS[a['status']]} · {a['question_count']} questions · {a['submission_count']} submissions"
            if a["code"]:
                details += f" · Code: {a['code']}"
            left.caption(details)
            if right.button("Open", key=f"open_{a['id']}"):
                st.session_state["selected_assessment"] = a["id"]
                st.rerun()


# ------------------------------------------------------------------ detail
def show_detail(aid):
    a = db.get_assessment(aid, teacher["id"])
    if a is None:
        st.session_state.pop("selected_assessment", None)
        st.rerun()

    flash = st.session_state.pop("flash", None)
    if st.button("Back to all assessments"):
        st.session_state.pop("selected_assessment", None)
        st.rerun()
    st.title(a["title"])
    st.caption(f"{STATUS[a['status']]} · {len(a['questions'])} questions · "
               f"{sum(q['marks'] for q in a['questions'])} marks")
    if flash:
        getattr(st, flash[0])(flash[1])

    if a["code"]:
        st.markdown("Students join with this code:")
        st.code(a["code"], language=None)
        st.caption("They open the app, choose 'Take an assessment' and enter it.")

    # --- controls
    if a["status"] == "draft":
        if st.button("Edit questions and publish", type="primary"):
            open_editor(aid)
    elif a["status"] == "published":
        if st.button("Close submissions"):
            db.set_status(aid, teacher["id"], "closed")
            st.rerun()
    else:
        if st.button("Reopen submissions"):
            db.set_status(aid, teacher["id"], "published")
            st.rerun()
    with st.expander("Delete this assessment"):
        sure = st.checkbox("I understand this also deletes all submissions and can't be undone.", key=f"sure_{aid}")
        if st.button("Delete assessment", disabled=not sure):
            db.delete_assessment(aid, teacher["id"])
            st.session_state.pop("selected_assessment", None)
            st.rerun()

    if a["status"] == "draft":
        return

    # --- submissions and scores
    st.divider()
    st.header("Submissions and scores")
    subs = db.list_submissions(aid, teacher["id"])
    if not subs:
        st.info("No submissions yet.")
        return

    qmap = {q["id"]: q for q in a["questions"]}
    out_of = sum(q["marks"] for q in a["questions"])
    rows, complete_pct = [], []
    pending_theory = []
    for s in subs:
        got = sum(x["awarded"] or 0 for x in s["answers"])
        pending = [x for x in s["answers"] if x["awarded"] is None]
        pending_theory += [x for x in pending if qmap[x["question_id"]]["type"] == "theory"]
        if not pending and out_of:
            complete_pct.append(100 * got / out_of)
        rows.append({"Student": s["student_name"], "ID": s["student_ref"], "Score": f"{got}/{out_of}",
                     "Percent": round(100 * got / out_of) if out_of else 0,
                     "Status": "Marked" if not pending else f"{len(pending)} to mark",
                     "Submitted": s["submitted_at"].strftime("%Y-%m-%d %H:%M")})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Submissions", len(subs))
    c2.metric("Average", f"{round(sum(complete_pct) / len(complete_pct))}%" if complete_pct else "-")
    c3.metric("Highest", f"{round(max(complete_pct))}%" if complete_pct else "-")
    c4.metric("Lowest", f"{round(min(complete_pct))}%" if complete_pct else "-")
    if len(complete_pct) < len(subs):
        st.caption("Average, highest and lowest only include students whose answers are fully marked.")

    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True)
    st.download_button("Download scores (CSV)", df.to_csv(index=False),
                       file_name=f"{a['title'].replace(' ', '_')}_scores.csv", mime="text/csv")

    # --- AI marking of theory answers
    if pending_theory:
        st.subheader("Mark written answers")
        st.caption("The AI marks each written answer against the model answer you set for the question. "
                   "Review its marks below and change any you disagree with.")
        api_key = get_api_key()
        if not api_key:
            st.caption("Add a Gemini API key in the sidebar to use AI marking.")
        if st.button(f"Mark {len(pending_theory)} written answer(s) with AI", disabled=not api_key):
            client = make_client(api_key)
            done, failed = 0, 0
            bar = st.progress(0.0)
            for i, x in enumerate(pending_theory, 1):
                q = qmap[x["question_id"]]
                try:
                    awarded, feedback = ai_mark_theory(client, q, x["response"])
                    db.update_answer(x["id"], teacher["id"], awarded, feedback, "ai")
                    done += 1
                except Exception:
                    failed += 1
                bar.progress(i / len(pending_theory))
            st.session_state["flash"] = (
                ("success", f"Marked {done} answer(s) with AI. Please review them below.") if not failed else
                ("warning", f"Marked {done}, but {failed} could not be marked. Try again, or mark them by hand."))
            st.rerun()

    # --- review and override
    st.subheader("Review answers")
    for s in subs:
        got = sum(x["awarded"] or 0 for x in s["answers"])
        todo = sum(1 for x in s["answers"] if x["awarded"] is None)
        label = f"{s['student_name']} - {got}/{out_of}" + (f"  ({todo} to mark)" if todo else "")
        with st.expander(label):
            with st.form(f"review_{s['id']}"):
                for x in s["answers"]:
                    q = qmap[x["question_id"]]
                    st.markdown(f"**{esc(q['text'])}**")
                    st.markdown(f"Student's answer: {esc(x['response']) if x['response'] else '_(blank)_'}")
                    st.caption(f"Correct answer: {esc(q['answer'])}")
                    st.number_input(f"Marks (out of {q['marks']})", min_value=0, max_value=q["marks"],
                                    value=x["awarded"], step=1, key=f"aw_{x['id']}")
                    if q["type"] == "theory":
                        st.text_area("Feedback", value=x["feedback"], key=f"fb_{x['id']}", height=68)
                    if x["graded_by"] == "ai":
                        st.caption("Marked by AI - please check.")
                    st.divider()
                saved = st.form_submit_button("Save marks")
            if saved:
                changed = 0
                for x in s["answers"]:
                    new_marks = st.session_state.get(f"aw_{x['id']}")
                    new_fb = st.session_state.get(f"fb_{x['id']}", x["feedback"])
                    if new_marks is None:
                        continue
                    if new_marks != x["awarded"] or new_fb != x["feedback"]:
                        db.update_answer(x["id"], teacher["id"], new_marks, new_fb, "teacher")
                        changed += 1
                st.session_state["flash"] = ("success", f"Saved {changed} change(s) for {s['student_name']}.")
                st.rerun()


selected = st.session_state.get("selected_assessment")
show_detail(selected) if selected else show_list()
