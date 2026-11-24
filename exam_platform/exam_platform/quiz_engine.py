"""
Core logic for the quiz generator (no Streamlit imports, so it is easy to test and reuse).

Pipeline: load file -> chunk -> embed -> retrieve -> generate -> verify -> (later) mark / grade.
"""

import difflib
import io
import json
import re
from pathlib import Path
from typing import Literal, Optional

import numpy as np
from google import genai
from google.genai import types
from pydantic import BaseModel

# Model names change over time - update these if Google deprecates them.
EMBED_MODEL = "gemini-embedding-001"
GEN_MODEL = "gemini-3.5-flash-lite"


def make_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------- schemas
class Question(BaseModel):
    type: Literal["mcq", "theory", "true_false", "fill_blank"]
    question: str
    options: list[str]    # MCQ: 4 options | true_false: ["True", "False"] | others: empty
    answer: str           # MCQ: 'B. ...' | true_false: 'True'/'False' | fill_blank: missing term | theory: model answer
    accepted: list[str]   # fill_blank only: other acceptable answers, else empty
    explanation: str      # why it's correct / marking points


class Quiz(BaseModel):
    questions: list[Question]


class Check(BaseModel):
    index: int        # 1-based question number
    supported: bool   # True only if the context clearly supports the question AND its answer
    reason: str


class Checks(BaseModel):
    checks: list[Check]


class Grade(BaseModel):
    score: int        # 0-5
    feedback: str


# ---------------------------------------------------------------- load + chunk
def load_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if suffix == ".docx":
        from docx import Document
        return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)

    if suffix in {".txt", ".md", ".csv"}:
        return data.decode("utf-8", errors="ignore")

    raise ValueError(f"Unsupported file type: {suffix}")


def chunk_text(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    text = " ".join(text.split())  # normalise whitespace
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


# ---------------------------------------------------------------- embed + retrieve
def embed(client, texts: list[str], task_type: str) -> np.ndarray:
    vectors = []
    for i in range(0, len(texts), 100):  # API batch limit
        res = client.models.embed_content(
            model=EMBED_MODEL,
            contents=texts[i:i + 100],
            config=types.EmbedContentConfig(task_type=task_type),
        )
        vectors.extend(e.values for e in res.embeddings)
    arr = np.array(vectors, dtype=np.float32)
    return arr / np.linalg.norm(arr, axis=1, keepdims=True)  # normalise for cosine


def retrieve(client, chunks: list[str], top_k: int, topic: Optional[str]) -> list[str]:
    top_k = min(top_k, len(chunks))

    if topic:
        # True RAG: the chunks most relevant to the topic
        chunk_vecs = embed(client, chunks, "RETRIEVAL_DOCUMENT")
        query_vec = embed(client, [topic], "RETRIEVAL_QUERY")[0]
        scores = chunk_vecs @ query_vec
        idx = sorted(np.argsort(scores)[::-1][:top_k])  # keep document order
    else:
        # No topic: sample evenly so the questions cover the whole document
        idx = sorted(set(np.linspace(0, len(chunks) - 1, top_k).astype(int)))

    return [chunks[i] for i in idx]


# ---------------------------------------------------------------- question types + sections
TYPE_RULES = {
    "mcq": "MULTIPLE CHOICE (type='mcq'): exactly 4 options; `answer` is the correct option like 'B. ...'.",
    "theory": "THEORY (type='theory'): a short-essay question; `options` is empty; `answer` is a concise model answer.",
    "true_false": "TRUE/FALSE (type='true_false'): `question` is one clear statement; `options` is ['True', 'False']; "
                  "`answer` is exactly 'True' or 'False'. Make about half of these false by subtly altering a fact from the context.",
    "fill_blank": "FILL IN THE BLANK (type='fill_blank'): `question` is a sentence from the context with ONE key term "
                  "replaced by _____; `options` is empty; `answer` is the missing term; "
                  "`accepted` lists other acceptable answers (synonyms, alternative spellings).",
}
ALL_TYPES = ["mcq", "true_false", "fill_blank", "theory"]

SECTION_ORDER = ALL_TYPES
SECTION_LETTERS = "ABCD"
SECTION_INFO = {
    # type: (title, instructions, marks per question)
    "mcq":        ("Multiple Choice", "Choose the one correct option.", "1 mark"),
    "true_false": ("True or False", "Decide whether each statement is true or false.", "1 mark"),
    "fill_blank": ("Fill in the Blank", "Write the missing word or phrase in each blank.", "1 mark"),
    "theory":     ("Theory", "Answer in your own words. Each answer is marked out of 5.", "5 marks"),
}
MAX_MARKS = {"mcq": 1, "true_false": 1, "fill_blank": 1, "theory": 5}


def resolve_types(question_type) -> list[str]:
    """Accepts 'mcq', 'mixed' (all types), or a list like ['mcq', 'true_false']."""
    if question_type == "mixed":
        return ALL_TYPES
    chosen = [question_type] if isinstance(question_type, str) else list(question_type)
    bad = [t for t in chosen if t not in TYPE_RULES]
    if bad or not chosen:
        raise ValueError(f"Unknown question type(s) {bad}. Choose from {list(TYPE_RULES)} or 'mixed'.")
    return chosen


def group_into_sections(quiz: Quiz):
    """Returns [(type, [questions]), ...] in fixed order, skipping types with no questions."""
    return [
        (t, [q for q in quiz.questions if q.type == t])
        for t in SECTION_ORDER
        if any(q.type == t for q in quiz.questions)
    ]


# ---------------------------------------------------------------- generate + verify
def _generate(client, prompt: str, schema, temperature: float):
    resp = client.models.generate_content(
        model=GEN_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=temperature,
        ),
    )
    return resp.parsed or schema(**json.loads(resp.text))


def verify_questions(client, quiz: Quiz, context: str):
    """Fact-check every question against the source text in ONE API call.
    Returns (kept_questions, [(rejected_question, reason), ...])."""
    numbered = "\n\n".join(
        f"{i}. [{q.type}] {q.question}\n   Options: {q.options}\n   Stated answer: {q.answer}"
        f"\n   Also accepted: {q.accepted}"
        for i, q in enumerate(quiz.questions, 1)
    )
    prompt = f"""You are a strict fact-checker. For each question below, decide whether the CONTEXT
clearly supports both the question and its stated answer.
Mark supported=false if the answer is wrong, not found in the context, ambiguous,
or if more than one MCQ option could be correct.
For true_false: mark supported=false if the statement is only partly true or needs outside knowledge.
For fill_blank: mark supported=false if the blank has other plausible answers that are not listed as accepted.
Return exactly one check per question.

CONTEXT:
{context}

QUESTIONS:
{numbered}
"""
    checks = _generate(client, prompt, Checks, temperature=0)
    verdicts = {c.index: c for c in checks.checks}

    kept, rejected = [], []
    for i, q in enumerate(quiz.questions, 1):
        c = verdicts.get(i)
        if c is None or c.supported:   # if the checker skipped one, keep it
            kept.append(q)
        else:
            rejected.append((q, c.reason))
    return kept, rejected


def generate_questions(
    client,
    filename: str,
    data: bytes,
    num_questions: int = 5,
    question_type="mixed",     # "mcq" | "true_false" | "fill_blank" | "theory" | "mixed" | a list of these
    topic: Optional[str] = None,
    difficulty: str = "medium",
    verify: bool = True,
):
    """Returns (quiz, rejected) where rejected is [(question, reason), ...] from verification."""
    chosen = resolve_types(question_type)

    text = load_text(filename, data)
    if not text.strip():
        raise ValueError("No text could be extracted from the file (is it a scanned PDF?).")

    chunks = chunk_text(text)
    context_chunks = retrieve(client, chunks, top_k=max(6, num_questions * 2), topic=topic)
    context = "\n\n---\n\n".join(context_chunks)

    rules = "\n".join(f"- {TYPE_RULES[t]}" for t in chosen)
    split = ("Split the questions roughly evenly across these types:"
             if len(chosen) > 1 else "Every question must be this type:")

    # Over-generate a little when verifying, so we still have enough after rejects
    n_request = num_questions + 2 if verify else num_questions
    topic_line = f"Focus on this topic: {topic}" if topic else ""

    prompt = f"""You are an exam setter. Using ONLY the context below, write {n_request} {difficulty}-difficulty questions.
{split}
{rules}
Set `accepted` to an empty list for every type except fill_blank.
Do not use outside knowledge. Each question must be answerable from the context.
Give a short `explanation` for every question.
{topic_line}

CONTEXT:
{context}
"""
    quiz = _generate(client, prompt, Quiz, temperature=0.4)

    rejected = []
    questions = quiz.questions
    if verify:
        questions, rejected = verify_questions(client, quiz, context)
    questions = questions[:num_questions]   # never return more than asked for

    # group questions into sections (all MCQs together, then T/F, ...)
    quiz = Quiz(questions=sorted(questions, key=lambda q: SECTION_ORDER.index(q.type)))
    return quiz, rejected


# ---------------------------------------------------------------- marking
def strip_label(opt: str) -> str:
    """Remove a leading 'A.' / 'B)' the model may have added to an option."""
    return re.sub(r"^\s*[A-Da-d][\.\)]\s*", "", opt)


def _norm(s: str) -> str:
    s = re.sub(r"[^\w\s]", "", s.lower())      # drop punctuation
    s = re.sub(r"\b(a|an|the)\b", "", s)       # drop articles
    return " ".join(s.split())


def check_fill_blank(q: Question, response: str) -> bool:
    """Exact match after normalising, or a close fuzzy match (typo tolerance)."""
    given = _norm(response)
    if not given:
        return False
    targets = [t for t in (_norm(a) for a in [q.answer] + list(q.accepted)) if t]
    return any(given == t or difflib.SequenceMatcher(None, given, t).ratio() >= 0.85 for t in targets)


def mark_objective(q: Question, response: Optional[str]) -> bool:
    """Marks mcq / true_false / fill_blank locally (no API call)."""
    if not response or not response.strip():
        return False
    if q.type == "mcq":
        return response.strip()[0].upper() == q.answer.strip()[0].upper()
    if q.type == "true_false":
        return q.answer.strip().lower().startswith(response.strip().lower())
    return check_fill_blank(q, response)


def grade_theory(client, q: Question, student_answer: str) -> Grade:
    """Have Gemini mark a free-text answer against the model answer."""
    prompt = f"""You are a fair examiner. Grade the student's answer from 0 to 5 against the model answer.
Give brief feedback: what was right and what was missing.

QUESTION: {q.question}
MODEL ANSWER: {q.answer}
MARKING NOTES: {q.explanation}
STUDENT ANSWER: {student_answer.strip() or "(blank)"}
"""
    g = _generate(client, prompt, Grade, temperature=0)
    g.score = max(0, min(5, g.score))
    return g
