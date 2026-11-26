import random
from datetime import timezone

import streamlit as st

import db
from app_config import require_student
from exam_timer import seconds_left, show_timer
from grading import SECTION_INSTRUCTIONS, SECTION_TITLES, auto_mark, group_dicts
from quiz_engine import SECTION_LETTERS, strip_label
from ui_utils import esc

EXAM_MINUTES = 30   # change to your exam length

student = require_student()
st.title("Take an assessment")

# ------------------------------------------------------------------ confirmation screen
done = st.session_state.get("take_done")
if done:
    if done.get("timed_out"):
        st.warning("Time is up. Your answers were submitted automatically.")
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

# ------------------------------------------------------------------ setup: clock, order, submit
a = state["assessment"]

# The start time is saved in the database, so refreshing the page can't restart the clock.
if "deadline" not in state:
    started = db.start_attempt(a["id"], student["id"])
    state["deadline"] = started.replace(tzinfo=timezone.utc).timestamp() + EXAM_MINUTES * 60
deadline = state["deadline"]


def exam_sections():
    """Questions grouped by section. Each student gets their own order inside every section,
    and it stays the same on reruns and refreshes (the random seed is student + assessment)."""
    rng = random.Random(f"{student['id']}-{a['id']}")
    sections = []
    for t, qs in group_dicts(a["questions"]):
        qs = list(qs)
        rng.shuffle(qs)
        sections.append((t, qs))
    return sections


sections = exam_sections()
all_questions = [q for _, qs in sections for q in qs]


def answer_key(q):
    return f"ans{state['nonce']}_{q['id']}"


def submit() -> bool:
    responses = {q["id"]: (st.session_state.get(answer_key(q)) or "") for q in all_questions}
    marks = {q["id"]: ((None, None) if q["type"] == "theory" else (auto_mark(q, responses[q["id"]]), "auto"))
             for q in all_questions}
    try:
        db.create_submission(a["id"], student["id"], responses, marks)
    except db.DuplicateError:
        st.error("You have already submitted this assessment.")
        return False
    except ValueError as e:
        st.error(str(e))
        return False
    objective = [q for q in all_questions if q["type"] != "theory"]
    st.session_state["take_done"] = dict(
        title=a["title"], show_score=a["show_score"],
        got=sum(marks[q["id"]][0] for q in objective),
        out_of=sum(q["marks"] for q in objective),
        pending=sum(1 for q in all_questions if q["type"] == "theory"))
    st.session_state.pop("take")
    return True


# Time is up: submit whatever the student has answered so far.
if seconds_left(deadline) <= 0:
    if submit():
        st.session_state["take_done"]["timed_out"] = True
        st.rerun()
    st.session_state.pop("take", None)   # couldn't submit (closed or duplicate), so stop the clock loop
    st.stop()

# ------------------------------------------------------------------ answer
st.subheader(a["title"])
st.caption(f"Taking as {student['name']}")
show_timer(deadline)            # shown at the top of the page
with st.sidebar:
    show_timer(deadline)        # also stays visible in the sidebar on desktop

n = 0
for letter, (t, qs) in zip(SECTION_LETTERS, sections):
    st.subheader(f"Section {letter}: {SECTION_TITLES[t]}")
    st.caption(SECTION_INSTRUCTIONS[t])
    for q in qs:
        n += 1
        key = answer_key(q)
        marks_label = f"{q['marks']} mark" + ("" if q["marks"] == 1 else "s")
        st.markdown(f"**Q{n}. {esc(q['text'])}** ({marks_label})")
        if q["type"] == "mcq":
            labels = [f"{l}. {strip_label(o)}" for l, o in zip("ABCD", q["options"])]
            st.radio("Answer", labels, index=None, key=key, format_func=esc, label_visibility="collapsed")
        elif q["type"] == "true_false":
            st.radio("Answer", ["True", "False"], index=None, key=key, label_visibility="collapsed")
        elif q["type"] == "fill_blank":
            st.text_input("Answer", key=key, placeholder="Your answer", label_visibility="collapsed")
        else:
            st.text_area("Answer", key=key, placeholder="Type your answer...", label_visibility="collapsed")

if st.button("Submit answers", type="primary"):
    if submit():
        st.rerun()