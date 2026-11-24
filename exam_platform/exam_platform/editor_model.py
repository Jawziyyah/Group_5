"""
Pure helpers for the question editor (no Streamlit), so they are easy to test.

An "editor question" is a flat dict the form widgets can edit directly:
    uid, type, text, options (4 strings for mcq), correct (A-D for mcq, True/False for true_false),
    answer_text (fill_blank / theory), accepted_text (comma-separated), explanation, marks
"""
import uuid

from quiz_engine import SECTION_ORDER, strip_label

TYPE_LABELS = {"mcq": "Multiple choice", "true_false": "True / False",
               "fill_blank": "Fill in the blank", "theory": "Theory"}
DEFAULT_MARKS = {"mcq": 1, "true_false": 1, "fill_blank": 1, "theory": 5}


def blank_question(qtype: str) -> dict:
    return dict(uid=uuid.uuid4().hex[:10], type=qtype, text="",
                options=["", "", "", ""] if qtype == "mcq" else [],
                correct={"mcq": "A", "true_false": "True"}.get(qtype, ""),
                answer_text="", accepted_text="", explanation="", marks=DEFAULT_MARKS[qtype])


def to_editor(q: dict) -> dict:
    """From the database/engine shape: {type, text, options, answer, accepted, explanation, marks}."""
    t = q["type"]
    e = blank_question(t)
    e["text"] = q.get("text", "")
    e["explanation"] = q.get("explanation", "")
    e["marks"] = int(q.get("marks") or DEFAULT_MARKS[t])
    ans = (q.get("answer") or "").strip()
    if t == "mcq":
        opts = [strip_label(o) for o in (q.get("options") or [])][:4]
        e["options"] = opts + [""] * (4 - len(opts))
        letter = ans[:1].upper()
        e["correct"] = letter if letter and letter in "ABCD" else "A"
    elif t == "true_false":
        e["correct"] = "False" if ans.lower().startswith("false") else "True"
    else:
        e["answer_text"] = ans
        e["accepted_text"] = ", ".join(q.get("accepted") or [])
    return e


def from_engine_question(q) -> dict:
    """From a quiz_engine.Question."""
    return to_editor(dict(type=q.type, text=q.question, options=q.options, answer=q.answer,
                          accepted=q.accepted, explanation=q.explanation, marks=None))


def from_editor(e: dict) -> dict:
    """To the database shape."""
    t = e["type"]
    out = dict(type=t, text=e["text"].strip(), options=[], answer="", accepted=[],
               explanation=e["explanation"].strip(), marks=int(e["marks"]))
    if t == "mcq":
        opts = [o.strip() for o in e["options"]]
        out["options"] = opts
        out["answer"] = f"{e['correct']}. {opts['ABCD'.index(e['correct'])]}"
    elif t == "true_false":
        out["options"] = ["True", "False"]
        out["answer"] = e["correct"]
    else:
        out["answer"] = e["answer_text"].strip()
        if t == "fill_blank":
            out["accepted"] = [a.strip() for a in e["accepted_text"].split(",") if a.strip()]
    return out


def validate(editors: list[dict]) -> list[str]:
    """Problems that would stop an assessment being published."""
    if not editors:
        return ["Add at least one question."]
    errors = []
    for n, e in enumerate(editors, 1):
        t = e["type"]
        if not e["text"].strip():
            errors.append(f"Q{n}: the question is empty.")
        if int(e["marks"]) < 1:
            errors.append(f"Q{n}: marks must be at least 1.")
        if t == "mcq":
            if any(not o.strip() for o in e["options"]):
                errors.append(f"Q{n}: all four options need text.")
            elif len({o.strip().lower() for o in e["options"]}) < 4:
                errors.append(f"Q{n}: two options are identical.")
        elif t == "fill_blank":
            if "___" not in e["text"]:
                errors.append(f"Q{n}: put _____ in the question where the blank goes.")
            if not e["answer_text"].strip():
                errors.append(f"Q{n}: the correct answer is empty.")
        elif t == "theory":
            if not e["answer_text"].strip():
                errors.append(f"Q{n}: add a model answer or marking guide.")
    return errors


def questions_for_db(editors: list[dict]) -> list[dict]:
    """Convert and group by section type (stable, so order within a type is kept)."""
    ordered = sorted(editors, key=lambda e: SECTION_ORDER.index(e["type"]))
    return [from_editor(e) for e in ordered]


def new_draft(title: str, source: str, questions: list[dict], notes: str = "", draft_id=None, show_score=True) -> dict:
    return dict(id=draft_id, nonce=uuid.uuid4().hex[:8], title=title, show_score=show_score,
                source=source, questions=questions, notes=notes)


def draft_from_generation(title: str, source: str, quiz, rejected) -> dict:
    notes = f"{len(rejected)} generated question(s) were removed by fact-checking." if rejected else ""
    return new_draft(title, source, [from_engine_question(q) for q in quiz.questions], notes)


def draft_from_db(a: dict) -> dict:
    return new_draft(a["title"], a["source_filename"], [to_editor(q) for q in a["questions"]],
                     draft_id=a["id"], show_score=a["show_score"])
