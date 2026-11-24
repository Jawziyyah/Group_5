"""Marking helpers that work on the plain dicts stored in the database."""
from quiz_engine import SECTION_ORDER, Question, grade_theory, mark_objective

SECTION_TITLES = {"mcq": "Multiple Choice", "true_false": "True or False",
                  "fill_blank": "Fill in the Blank", "theory": "Theory"}
SECTION_INSTRUCTIONS = {
    "mcq": "Choose the one correct option.",
    "true_false": "Decide whether each statement is true or false.",
    "fill_blank": "Write the missing word or phrase in each blank.",
    "theory": "Answer in your own words.",
}


def group_dicts(questions: list[dict]):
    """[(type, [questions]), ...] in fixed section order, skipping empty sections."""
    return [(t, [q for q in questions if q["type"] == t])
            for t in SECTION_ORDER if any(q["type"] == t for q in questions)]


def to_question(q: dict) -> Question:
    return Question(type=q["type"], question=q["text"], options=q["options"], answer=q["answer"],
                    accepted=q["accepted"], explanation=q["explanation"])


def auto_mark(q: dict, response) -> int:
    """Full marks or zero for mcq / true_false / fill_blank."""
    return q["marks"] if mark_objective(to_question(q), response) else 0


def ai_mark_theory(client, q: dict, response):
    """Returns (marks, feedback). Gemini scores 0-5 against the teacher's model answer; we scale to the question's marks."""
    if not (response or "").strip():
        return 0, "No answer given."
    g = grade_theory(client, to_question(q), response)
    awarded = max(0, min(q["marks"], round(g.score / 5 * q["marks"])))
    return awarded, g.feedback
