"""Small helpers shared by the student and teacher pages."""


def numbered(questions: list[dict]) -> list[dict]:
    """Return copies of the questions in order, each with a 'number' key (1, 2, 3...)."""
    ordered = sorted(questions, key=lambda q: q.get("position", 0))
    return [dict(q, number=i) for i, q in enumerate(ordered, start=1)]
