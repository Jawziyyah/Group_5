import uuid
from pathlib import Path

import streamlit as st

import db
import editor_model as em
from app_config import get_api_key, require_teacher
from quiz_engine import generate_questions, make_client

teacher = require_teacher()
st.title("Create assessment")


# ------------------------------------------------------------------ state helpers
def sync_from_widgets():
    """Copy what is currently typed into the widgets back into the draft."""
    d = st.session_state.get("draft")
    if not d:
        return
    s, n = st.session_state, d["nonce"]
    d["title"] = s.get(f"{n}_title", d["title"])
    d["show_score"] = s.get(f"{n}_show", d["show_score"])
    for q in d["questions"]:
        k = f"{n}_{q['uid']}"
        q["text"] = s.get(f"{k}_text", q["text"])
        q["explanation"] = s.get(f"{k}_expl", q["explanation"])
        q["marks"] = s.get(f"{k}_marks", q["marks"])
        if q["type"] == "mcq":
            q["options"] = [s.get(f"{k}_opt{i}", q["options"][i]) for i in range(4)]
            q["correct"] = s.get(f"{k}_correct", q["correct"])
        elif q["type"] == "true_false":
            q["correct"] = s.get(f"{k}_correct", q["correct"])
        else:
            q["answer_text"] = s.get(f"{k}_answer", q["answer_text"])
            q["accepted_text"] = s.get(f"{k}_accepted", q["accepted_text"])


def delete_question(uid):
    sync_from_widgets()
    d = st.session_state["draft"]
    d["questions"] = [q for q in d["questions"] if q["uid"] != uid]


def add_question():
    sync_from_widgets()
    st.session_state["draft"]["questions"].append(em.blank_question(st.session_state["add_type"]))


def persist(d) -> int:
    """Save the draft to the database (create or update). Returns the assessment id."""
    questions = em.questions_for_db(d["questions"])
    if d["id"] is None:
        d["id"] = db.create_assessment(teacher["id"], d["title"], questions, d["source"], d["show_score"])
    else:
        db.save_draft(d["id"], teacher["id"], d["title"], d["show_score"], questions)
    return d["id"]


# ------------------------------------------------------------------ pick up "edit this draft" from the list page
if st.session_state.get("draft") is None and st.session_state.get("editing_id"):
    a = db.get_assessment(st.session_state["editing_id"], teacher["id"])
    if a and a["status"] == "draft":
        st.session_state["draft"] = em.draft_from_db(a)
    st.session_state["editing_id"] = None

# ------------------------------------------------------------------ just published banner
published = st.session_state.get("just_published")
if published:
    st.success(f"**{published['title']}** is published. Give students this code:")
    st.code(published["code"], language=None)
    st.caption("Students open the app, choose 'Take an assessment' and enter the code. "
               "You can see submissions and scores under My assessments.")
    if st.button("Create another assessment"):
        st.session_state.pop("just_published")
        st.rerun()
    st.stop()

draft = st.session_state.get("draft")

# ------------------------------------------------------------------ step 1: generate or start blank
if draft is None:
    st.subheader("1. Generate questions from a file")
    api_key = get_api_key()
    file = st.file_uploader("Lesson notes, a textbook chapter or any document", type=["pdf", "docx", "txt", "md"])
    title = st.text_input("Assessment title", placeholder="e.g. Cell biology - week 3 quiz")
    c1, c2 = st.columns(2)
    chosen = c1.multiselect("Question types", list(em.TYPE_LABELS), default=list(em.TYPE_LABELS),
                            format_func=em.TYPE_LABELS.get)
    num = c2.slider("Number of questions", 3, 20, 8)
    c3, c4 = st.columns(2)
    difficulty = c3.selectbox("Difficulty", ["easy", "medium", "hard"], index=1)
    topic = c4.text_input("Focus topic (optional)")
    verify = st.checkbox("Fact-check questions against the file", value=True)

    missing = []
    if not api_key:
        missing.append("a Gemini API key (sidebar)")
    if not file:
        missing.append("a file")
    if not chosen:
        missing.append("at least one question type")
    if missing:
        st.info("To generate, add " + ", ".join(missing) + ".")

    if st.button("Generate questions", type="primary", disabled=bool(missing)):
        with st.spinner("Reading the file and writing questions..."):
            try:
                quiz, rejected = generate_questions(
                    make_client(api_key), file.name, file.getvalue(), num_questions=num,
                    question_type=chosen, topic=topic.strip() or None, difficulty=difficulty, verify=verify)
            except Exception as e:
                st.error(f"Could not generate questions: {e}")
            else:
                st.session_state["draft"] = em.draft_from_generation(
                    title.strip() or Path(file.name).stem, file.name, quiz, rejected)
                st.rerun()

    st.divider()
    st.subheader("Or start from scratch")
    if st.button("Start with a blank assessment"):
        st.session_state["draft"] = em.new_draft("", "", [])
        st.rerun()
    st.stop()

# ------------------------------------------------------------------ step 2: edit
n = draft["nonce"]
st.subheader("2. Review and edit")
if draft["notes"]:
    st.info(draft["notes"])
st.caption("Everything below can be changed. The correct answers and marking notes you set here are what students "
           "are marked against, so check them carefully.")

st.text_input("Assessment title", value=draft["title"], key=f"{n}_title")
st.checkbox("Show students their auto-marked score after they submit", value=draft["show_score"], key=f"{n}_show")

for i, q in enumerate(draft["questions"], 1):
    k = f"{n}_{q['uid']}"
    with st.container(border=True):
        head, delete = st.columns([5, 1])
        head.markdown(f"**Q{i}. {em.TYPE_LABELS[q['type']]}**")
        delete.button("Delete", key=f"{k}_del", on_click=delete_question, args=(q["uid"],))
        st.text_area("Question", value=q["text"], key=f"{k}_text", height=80)
        if q["type"] == "mcq":
            for j, letter in enumerate("ABCD"):
                st.text_input(f"Option {letter}", value=q["options"][j], key=f"{k}_opt{j}")
            st.radio("Correct option", list("ABCD"), index="ABCD".index(q["correct"]),
                     horizontal=True, key=f"{k}_correct")
        elif q["type"] == "true_false":
            st.radio("Correct answer", ["True", "False"], index=["True", "False"].index(q["correct"]),
                     horizontal=True, key=f"{k}_correct")
        elif q["type"] == "fill_blank":
            st.caption("Write _____ in the question where the blank goes.")
            st.text_input("Correct answer (the missing term)", value=q["answer_text"], key=f"{k}_answer")
            st.text_input("Other accepted answers (comma-separated)", value=q["accepted_text"], key=f"{k}_accepted")
        else:
            st.text_area("Model answer / marking guide", value=q["answer_text"], key=f"{k}_answer", height=100)
        st.text_area("Explanation / marking notes", value=q["explanation"], key=f"{k}_expl", height=68)
        st.number_input("Marks", min_value=1, max_value=50, value=int(q["marks"]), step=1, key=f"{k}_marks")

add_col, btn_col = st.columns([3, 1])
add_col.selectbox("Add a question", list(em.TYPE_LABELS), format_func=em.TYPE_LABELS.get,
                  key="add_type", label_visibility="collapsed")
btn_col.button("Add question", on_click=add_question)

# ------------------------------------------------------------------ step 3: save / publish
st.divider()
total = sum(int(st.session_state.get(f"{n}_{q['uid']}_marks", q["marks"])) for q in draft["questions"])
st.caption(f"{len(draft['questions'])} question(s), {total} marks in total.")
save_col, pub_col, discard_col = st.columns(3)

if save_col.button("Save draft"):
    sync_from_widgets()
    if not draft["title"].strip():
        st.error("Give the assessment a title first.")
    else:
        persist(draft)
        st.success("Draft saved. You'll find it under My assessments.")

if pub_col.button("Publish", type="primary"):
    sync_from_widgets()
    problems = [] if draft["title"].strip() else ["Give the assessment a title."]
    problems += em.validate(draft["questions"])
    if problems:
        st.error("Fix these before publishing:\n\n" + "\n".join(f"- {p}" for p in problems))
    else:
        try:
            aid = persist(draft)
            code = db.publish_assessment(aid, teacher["id"])
        except Exception as e:
            st.error(f"Could not publish: {e}")
        else:
            st.session_state["just_published"] = dict(title=draft["title"], code=code)
            st.session_state.pop("draft", None)
            st.rerun()

if discard_col.button("Discard changes"):
    st.session_state.pop("draft", None)
    st.rerun()
