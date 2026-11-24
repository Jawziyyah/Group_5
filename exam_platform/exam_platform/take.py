import streamlit as st

import db
from app_config import require_student
from grading import SECTION_INSTRUCTIONS, SECTION_TITLES, auto_mark, group_dicts
from quiz_engine import SECTION_LETTERS, strip_label
from ui_utils import esc

student = require_student()
st.title("Take an assessment")

# ------------------------------------------------------------------ confirmation screen
done = st.session_state.get("take_done")
if done:
    st.success(f"Your answers for **{esc(done['title'])}** have been submitted.")
    if done["show_score"]:
        st.metric("Auto-marked score", f"{done['got']}/{done['out_of']}")
        if done["pending"]:
            st.caption(f"{done['pending']} written answer(s) will be marked by your teacher.")
    else:
        st.caption("Your teacher will share your results.")
    st.caption("When your teacher releases the results, you'll find them on My dashboard.")
    if st.button("Take another assessment"):
        st.session_state.pop("take_done")
        st.rerun()
    st.stop()

# ------------------------------------------------------------------ enter the code
state = st.session_state.get("take")
if not state:
    st.caption("Enter the code your teacher gave you.")
    with st.form("join_form"):
        code = st.text_input("Assessment code", max_chars=12)
        go = st.form_submit_button("Start", type="primary")
    if go:
        a = db.get_assessment_by_code(code) if code.strip() else None
        if a is None:
            st.error("We couldn't find that code. Check it and try again.")
        elif a["status"] != "published":
            st.error("This assessment is closed and no longer accepting submissions.")
        elif db.student_has_submitted(a["id"], student["id"]):
            st.error("You have already submitted this assessment. You can see it on My dashboard.")
        else:
            st.session_state["take_count"] = st.session_state.get("take_count", 0) + 1
            st.session_state["take"] = dict(assessment=a, nonce=st.session_state["take_count"])
            st.rerun()
    st.stop()

# ------------------------------------------------------------------ answer
a = state["assessment"]
st.subheader(a["title"])
st.caption(f"Taking as {student['name']}")

fields = []   # (question, widget key)
with st.form("take_form"):
    n = 0
    for letter, (t, qs) in zip(SECTION_LETTERS, group_dicts(a["questions"])):
        st.subheader(f"Section {letter}: {SECTION_TITLES[t]}")
        st.caption(SECTION_INSTRUCTIONS[t])
        for q in qs:
            n += 1
            key = f"ans{state['nonce']}_{q['id']}"
            marks = f"{q['marks']} mark" + ("" if q["marks"] == 1 else "s")
            st.markdown(f"**Q{n}. {esc(q['text'])}** ({marks})")
            if q["type"] == "mcq":
                labels = [f"{l}. {strip_label(o)}" for l, o in zip("ABCD", q["options"])]
                st.radio("Answer", labels, index=None, key=key, format_func=esc, label_visibility="collapsed")
            elif q["type"] == "true_false":
                st.radio("Answer", ["True", "False"], index=None, key=key, label_visibility="collapsed")
            elif q["type"] == "fill_blank":
                st.text_input("Answer", key=key, placeholder="Your answer", label_visibility="collapsed")
            else:
                st.text_area("Answer", key=key, placeholder="Type your answer...", label_visibility="collapsed")
            fields.append((q, key))
    submitted = st.form_submit_button("Submit answers", type="primary")

if submitted:
    responses = {q["id"]: (st.session_state.get(key) or "") for q, key in fields}
    marks = {q["id"]: ((None, None) if q["type"] == "theory" else (auto_mark(q, responses[q["id"]]), "auto"))
             for q, _ in fields}
    try:
        db.create_submission(a["id"], student["id"], responses, marks)
    except db.DuplicateError:
        st.error("You have already submitted this assessment.")
    except ValueError as e:
        st.error(str(e))
    else:
        objective = [q for q, _ in fields if q["type"] != "theory"]
        st.session_state["take_done"] = dict(
            title=a["title"], show_score=a["show_score"],
            got=sum(marks[q["id"]][0] for q in objective),
            out_of=sum(q["marks"] for q in objective),
            pending=sum(1 for q, _ in fields if q["type"] == "theory"))
        st.session_state.pop("take")
        st.rerun()
