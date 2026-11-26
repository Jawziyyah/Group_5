import pandas as pd
import streamlit as st

import analytics as an
import db
import reports
from app_config import get_api_key, require_teacher
from grading import SECTION_TITLES, ai_mark_theory
from quiz_engine import make_client
from ui_utils import esc

teacher = require_teacher()
STATUS = {"draft": "Draft", "published": "Open", "closed": "Closed"}


@st.cache_data(show_spinner=False, max_entries=20)
def _class_pdf(assessment, submissions) -> bytes:
    return reports.class_report_pdf(assessment, submissions)


@st.cache_data(show_spinner=False, max_entries=20)
def _sheets_pdf(assessment, submissions) -> bytes:
    return reports.feedback_sheets_pdf(assessment, submissions)


def open_editor(assessment_id=None):
    st.session_state.pop("draft", None)
    st.session_state["editing_id"] = assessment_id
    st.switch_page("views/create.py")


def flash(kind, message):
    st.session_state["flash"] = (kind, message)
    st.rerun()


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

    message = st.session_state.pop("flash", None)
    if st.button("Back to all assessments"):
        st.session_state.pop("selected_assessment", None)
        st.rerun()
    st.title(a["title"])
    status = f"{STATUS[a['status']]} · {len(a['questions'])} questions · {sum(q['marks'] for q in a['questions'])} marks"
    if a["status"] != "draft":
        status += " · Results released to students" if a["results_released"] else " · Results not released yet"
    st.caption(status)
    if message:
        getattr(st, message[0])(message[1])

    if a["code"]:
        st.markdown("Students join with this code:")
        st.code(a["code"], language=None)
        st.caption("They sign in to the student portal, choose 'Take an assessment' and enter it.")

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

    # --- scores
    st.divider()
    st.header("Submissions and scores")
    subs = db.list_submissions(aid, teacher["id"])
    if not subs:
        st.info("No submissions yet.")
        return

    qmap = {q["id"]: q for q in a["questions"]}
    out_of = sum(q["marks"] for q in a["questions"])
    rows = an.student_totals(subs, a["questions"])
    summ = an.summary(rows)
    pending_theory = [x for s in subs for x in s["answers"]
                      if x["awarded"] is None and qmap[x["question_id"]]["type"] == "theory"]

    pct = lambda v: "-" if v is None else f"{v}%"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Submissions", summ["submissions"])
    c2.metric("Average", pct(summ["average"]))
    c3.metric("Highest", pct(summ["highest"]))
    c4.metric("Lowest", pct(summ["lowest"]))
    if summ["complete"] < summ["submissions"]:
        st.caption("Average, highest and lowest only include students whose answers are fully marked.")

    df = pd.DataFrame([{"Student": r["name"], "ID": r["ref"], "Score": f"{r['got']}/{r['out_of']}",
                        "Percent": r["pct"], "Status": "Marked" if not r["pending"] else f"{r['pending']} to mark",
                        "Submitted": r["submitted_at"].strftime("%Y-%m-%d %H:%M")} for r in rows])
    st.dataframe(df, hide_index=True)

    if summ["complete"]:
        st.caption("Score distribution (percent of marks, fully marked students)")
        dist = an.distribution(rows)
        st.bar_chart(pd.DataFrame({"Students": [n for _, n in dist]}, index=[label for label, _ in dist]))

    safe = a["title"].replace(" ", "_")
    d1, d2, d3 = st.columns(3)
    d1.download_button("Scores (CSV)", df.to_csv(index=False), file_name=f"{safe}_scores.csv", mime="text/csv")
    d2.download_button("Class report (PDF)", _class_pdf(a, subs), file_name=f"{safe}_class_report.pdf",
                       mime="application/pdf")
    d3.download_button("Feedback sheets (PDF)", _sheets_pdf(a, subs), file_name=f"{safe}_feedback_sheets.pdf",
                       mime="application/pdf", help="One page per student, ready to print and hand out.")

    # --- question analysis
    st.divider()
    st.header("Question analysis")
    qstats = an.question_stats(a["questions"], subs)
    if not any(s["n"] for s in qstats):
        st.info("This appears once some answers have been marked.")
    else:
        hard = an.struggled(qstats)
        if hard:
            st.markdown(f"**Students struggled with** (class average below {an.STRUGGLE_THRESHOLD}%):")
            for s in hard:
                line = f"- **Q{s['number']}** ({s['avg_pct']}%): {esc(s['text'][:120])}"
                if s["common_wrong"]:
                    line += f"  \n  Common wrong answers: {esc(s['common_wrong'])}"
                st.markdown(line)
        else:
            st.success(f"No question averaged below {an.STRUGGLE_THRESHOLD}%.")
        st.caption("Average score per question (percent of marks)")
        chart = [s for s in qstats if s["avg_pct"] is not None]
        st.bar_chart(pd.DataFrame({"Average %": [s["avg_pct"] for s in chart]},
                                  index=[f"Q{s['number']:02d}" for s in chart]))
        st.dataframe(pd.DataFrame([{
            "Q": s["number"], "Type": SECTION_TITLES[s["type"]],
            "Question": s["text"] if len(s["text"]) <= 70 else s["text"][:67] + "...",
            "Marks": s["marks"], "Average %": s["avg_pct"],
            "Full marks": f"{s['full_marks']}/{s['n']}" if s["n"] else "-",
            "Common wrong answers": s["common_wrong"] or ""} for s in qstats]), hide_index=True)

    # --- AI marking of theory answers
    if pending_theory:
        st.divider()
        st.header("Mark written answers")
        st.caption("The AI marks each written answer against the model answer you set for the question. "
                   "Review its marks below and change any you disagree with.")
        api_key = get_api_key()
        if not api_key:
            st.caption("Add a Gemini API key in the sidebar to use AI marking.")
        if st.button(f"Mark {len(pending_theory)} written answer(s) with AI", disabled=not api_key):
            client = make_client(api_key)
            done = failed = 0
            bar = st.progress(0.0)
            for i, x in enumerate(pending_theory, 1):
                try:
                    awarded, feedback = ai_mark_theory(client, qmap[x["question_id"]], x["response"])
                    db.update_answer(x["id"], teacher["id"], awarded, feedback, "ai")
                    done += 1
                except Exception:
                    failed += 1
                bar.progress(i / len(pending_theory))
            flash(*(("success", f"Marked {done} answer(s) with AI. Please review them below.") if not failed else
                    ("warning", f"Marked {done}, but {failed} could not be marked. Try again, or mark them by hand.")))

    # --- review and override
    st.divider()
    st.header("Review answers")
    for s, r in zip(subs, rows):
        label = f"{s['student_name']} - {r['got']}/{out_of}" + (f"  ({r['pending']} to mark)" if r["pending"] else "")
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
                flash("success", f"Saved {changed} change(s) for {s['student_name']}.")

    # --- release
    st.divider()
    st.header("Release results")
    unmarked = sum(r["pending"] for r in rows)
    if a["results_released"]:
        st.success("Results are released. Students can see their marks, answers and feedback on their dashboard.")
        if st.button("Hide results again"):
            db.set_results_released(aid, teacher["id"], False)
            flash("success", "Results are hidden from students again.")
    else:
        st.caption("Students can't see their marks until you release them. Check the AI's marks above first.")
        allowed = True
        if unmarked:
            st.warning(f"{unmarked} answer(s) aren't marked yet. Students would see them as 'not marked yet'.")
            allowed = st.checkbox("Release anyway", key=f"release_anyway_{aid}")
        if st.button("Release results to students", type="primary", disabled=not allowed):
            db.set_results_released(aid, teacher["id"], True)
            flash("success", "Results released. Students can now view them.")


selected = st.session_state.get("selected_assessment")
show_detail(selected) if selected else show_list()
