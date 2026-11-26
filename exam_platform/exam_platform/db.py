"""
Database layer (SQLAlchemy).

SQLite by default (a local file). On hosted deployments such as Streamlit Community Cloud the
filesystem is wiped on restart, so set DATABASE_URL to a Postgres database (Supabase, Neon, ...)
to keep your data.

Every function returns plain dicts, so nothing depends on an open database session.
"""

import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
    create_engine, inspect, or_, select, text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I, easy to read out loud
CODE_LENGTH = 6


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DuplicateError(Exception):
    """Raised when something that must be unique already exists."""


class Base(DeclarativeBase):
    pass


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    student_ref: Mapped[str] = mapped_column(String(60), default="")   # matric / admission number
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Assessment(Base):
    __tablename__ = "assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    source_filename: Mapped[str] = mapped_column(String(255), default="")
    code: Mapped[Optional[str]] = mapped_column(String(12), unique=True, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="draft")   # draft | published | closed
    show_score: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    questions: Mapped[list["Question"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", order_by="Question.position")
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", order_by="Submission.submitted_at")


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(20))       # mcq | true_false | fill_blank | theory
    text: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)
    answer: Mapped[str] = mapped_column(Text, default="")
    accepted: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    marks: Mapped[int] = mapped_column(Integer, default=1)
    assessment: Mapped["Assessment"] = relationship(back_populates="questions")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("assessment_id", "student_key", name="one_submission_per_student"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), index=True)
    student_id: Mapped[Optional[int]] = mapped_column(ForeignKey("students.id"), index=True, nullable=True)
    student_name: Mapped[str] = mapped_column(String(120))
    student_ref: Mapped[str] = mapped_column(String(60), default="")
    student_key: Mapped[str] = mapped_column(String(200))
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    # Optional integrity data (tab switches, paste events, risk level...) saved by the exam guard.
    integrity_report: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    assessment: Mapped["Assessment"] = relationship(back_populates="submissions")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", order_by="Answer.id")


class Answer(Base):
    __tablename__ = "answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    response: Mapped[str] = mapped_column(Text, default="")
    awarded: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # None = not marked yet
    feedback: Mapped[str] = mapped_column(Text, default="")
    graded_by: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)   # auto | ai | teacher
    submission: Mapped["Submission"] = relationship(back_populates="answers")


class Attempt(Base):
    """When a student started an assessment. Stored so refreshing the page can't restart the timer."""
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("assessment_id", "student_id", name="one_attempt_per_student"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ------------------------------------------------------------------ engine
_engine = None


def _migrate(engine) -> None:
    """Add columns introduced after the first version to an EXISTING database.
    create_all() creates missing tables but never adds columns to tables that already exist."""
    insp = inspect(engine)
    if "submissions" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("submissions")}
    wanted = {"student_id": "INTEGER", "integrity_report": "JSON"}
    with engine.begin() as con:
        for col, ddl in wanted.items():
            if col not in existing:
                con.execute(text(f"ALTER TABLE submissions ADD COLUMN {col} {ddl}"))


def init(url: Optional[str] = None, force: bool = False):
    """Create the engine and tables once. Safe to call on every Streamlit rerun."""
    global _engine
    if _engine is not None and not force:
        return _engine
    url = url or "sqlite:///exam_platform.db"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **kwargs)
    Base.metadata.create_all(_engine)
    _migrate(_engine)
    return _engine


def _session() -> Session:
    if _engine is None:
        init()
    return Session(_engine)


# ------------------------------------------------------------------ dict helpers
def _question_dict(q: Question) -> dict:
    return dict(id=q.id, position=q.position, type=q.type, text=q.text, options=list(q.options or []),
                answer=q.answer, accepted=list(q.accepted or []), explanation=q.explanation or "", marks=q.marks)


def _assessment_dict(a: Assessment, with_questions: bool = True) -> dict:
    d = dict(id=a.id, teacher_id=a.teacher_id, title=a.title, source_filename=a.source_filename,
             code=a.code, status=a.status, show_score=a.show_score, created_at=a.created_at,
             published_at=a.published_at)
    if with_questions:
        d["questions"] = [_question_dict(q) for q in a.questions]
    return d


def _answer_dict(x: Answer) -> dict:
    return dict(id=x.id, question_id=x.question_id, response=x.response,
                awarded=x.awarded, feedback=x.feedback or "", graded_by=x.graded_by)


def _owned(s: Session, assessment_id: int, teacher_id: int) -> Assessment:
    a = s.get(Assessment, assessment_id)
    if a is None:
        raise LookupError("Assessment not found.")
    if a.teacher_id != teacher_id:
        raise PermissionError("This assessment belongs to another teacher.")
    return a


# ------------------------------------------------------------------ teachers
def create_teacher(email: str, name: str, password_hash: str) -> dict:
    with _session() as s:
        t = Teacher(email=email.strip().lower(), name=name.strip(), password_hash=password_hash)
        s.add(t)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise DuplicateError("An account with this email already exists.")
        return dict(id=t.id, email=t.email, name=t.name)


def get_teacher_by_email(email: str) -> Optional[dict]:
    with _session() as s:
        t = s.scalar(select(Teacher).where(Teacher.email == email.strip().lower()))
        return None if t is None else dict(id=t.id, email=t.email, name=t.name, password_hash=t.password_hash)


# ------------------------------------------------------------------ students
def _student_dict(st: Student, with_hash: bool = False) -> dict:
    d = dict(id=st.id, email=st.email, name=st.name, student_ref=st.student_ref or "")
    if with_hash:
        d["password_hash"] = st.password_hash
    return d


def create_student(email: str, name: str, ref: str, password_hash: str) -> dict:
    with _session() as s:
        st = Student(email=email.strip().lower(), name=name.strip(),
                     student_ref=(ref or "").strip(), password_hash=password_hash)
        s.add(st)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise DuplicateError("An account with this email already exists.")
        return _student_dict(st)


def get_student_by_email(email: str) -> Optional[dict]:
    """Includes password_hash, for login checks."""
    with _session() as s:
        st = s.scalar(select(Student).where(Student.email == email.strip().lower()))
        return None if st is None else _student_dict(st, with_hash=True)


def get_student(student_id: int) -> Optional[dict]:
    with _session() as s:
        st = s.get(Student, student_id)
        return None if st is None else _student_dict(st)


def update_student_password(student_id: int, password_hash: str) -> None:
    with _session() as s:
        st = s.get(Student, student_id)
        if st is None:
            raise LookupError("Student not found.")
        st.password_hash = password_hash
        s.commit()


def update_student_profile(student_id: int, name: str, ref: str) -> dict:
    """Note: submissions already made keep the name/reference they were submitted with."""
    with _session() as s:
        st = s.get(Student, student_id)
        if st is None:
            raise LookupError("Student not found.")
        st.name = name.strip() or st.name
        st.student_ref = (ref or "").strip()
        s.commit()
        return _student_dict(st)


# ------------------------------------------------------------------ assessments
def _set_questions(a: Assessment, questions: list[dict]) -> None:
    a.questions = [
        Question(position=i, type=q["type"], text=q["text"], options=q.get("options") or [],
                 answer=q.get("answer", ""), accepted=q.get("accepted") or [],
                 explanation=q.get("explanation", ""), marks=int(q.get("marks") or 1))
        for i, q in enumerate(questions)
    ]


def create_assessment(teacher_id: int, title: str, questions: list[dict],
                      source_filename: str = "", show_score: bool = True) -> int:
    with _session() as s:
        a = Assessment(teacher_id=teacher_id, title=title.strip() or "Untitled assessment",
                       source_filename=source_filename, show_score=show_score)
        _set_questions(a, questions)
        s.add(a)
        s.commit()
        return a.id


def save_draft(assessment_id: int, teacher_id: int, title: str, show_score: bool, questions: list[dict]) -> None:
    with _session() as s:
        a = _owned(s, assessment_id, teacher_id)
        if a.status != "draft":
            raise ValueError("Only drafts can be edited. This assessment has already been published.")
        a.title = title.strip() or "Untitled assessment"
        a.show_score = show_score
        _set_questions(a, questions)
        s.commit()


def _unique_code(s: Session) -> str:
    for _ in range(50):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if s.scalar(select(Assessment.id).where(Assessment.code == code)) is None:
            return code
    raise RuntimeError("Could not generate a unique code.")


def publish_assessment(assessment_id: int, teacher_id: int) -> str:
    with _session() as s:
        a = _owned(s, assessment_id, teacher_id)
        if not a.questions:
            raise ValueError("Add at least one question before publishing.")
        if a.code is None:
            a.code = _unique_code(s)
        a.status = "published"
        a.published_at = a.published_at or _now()
        s.commit()
        return a.code


def set_status(assessment_id: int, teacher_id: int, status: str) -> None:
    if status not in ("published", "closed"):
        raise ValueError("Status must be 'published' or 'closed'.")
    with _session() as s:
        a = _owned(s, assessment_id, teacher_id)
        if a.code is None:
            raise ValueError("Publish the assessment first.")
        a.status = status
        s.commit()


def delete_assessment(assessment_id: int, teacher_id: int) -> None:
    with _session() as s:
        s.delete(_owned(s, assessment_id, teacher_id))
        s.commit()


def list_assessments(teacher_id: int) -> list[dict]:
    with _session() as s:
        rows = s.scalars(select(Assessment).where(Assessment.teacher_id == teacher_id)
                         .order_by(Assessment.created_at.desc(), Assessment.id.desc())).all()
        return [dict(_assessment_dict(a, with_questions=False),
                     question_count=len(a.questions), submission_count=len(a.submissions)) for a in rows]


def get_assessment(assessment_id: int, teacher_id: int) -> Optional[dict]:
    with _session() as s:
        a = s.get(Assessment, assessment_id)
        if a is None or a.teacher_id != teacher_id:
            return None
        return _assessment_dict(a)


def get_assessment_by_code(code: str) -> Optional[dict]:
    """Used by students. Drafts are never visible."""
    with _session() as s:
        a = s.scalar(select(Assessment).where(Assessment.code == code.strip().upper()))
        if a is None or a.status not in ("published", "closed"):
            return None
        return _assessment_dict(a)


# ------------------------------------------------------------------ submissions
def _student_key(name: str, ref: str) -> str:
    return f"{' '.join(name.lower().split())}|{ref.strip().lower()}"


def student_exists(assessment_id: int, name: str, ref: str = "") -> bool:
    """True if a student with this name + reference has already submitted this assessment."""
    with _session() as s:
        return s.scalar(select(Submission.id).where(
            Submission.assessment_id == assessment_id,
            Submission.student_key == _student_key(name, ref))) is not None


def student_has_submitted(assessment_id: int, student_id: int) -> bool:
    """Same check for a logged-in student. Also catches older submissions made by name + reference."""
    with _session() as s:
        st = s.get(Student, student_id)
        if st is None:
            return False
        return s.scalar(select(Submission.id).where(
            Submission.assessment_id == assessment_id,
            or_(Submission.student_id == student_id,
                Submission.student_key == _student_key(st.name, st.student_ref)))) is not None


def start_attempt(assessment_id: int, student_id: int) -> datetime:
    """Returns when this student started the assessment (UTC). The first call records the start;
    later calls (for example after a page refresh) return the same time."""
    with _session() as s:
        row = s.scalar(select(Attempt).where(Attempt.assessment_id == assessment_id,
                                             Attempt.student_id == student_id))
        if row is None:
            row = Attempt(assessment_id=assessment_id, student_id=student_id)
            s.add(row)
            try:
                s.commit()
            except IntegrityError:        # two tabs started at once
                s.rollback()
                row = s.scalar(select(Attempt).where(Attempt.assessment_id == assessment_id,
                                                     Attempt.student_id == student_id))
        return row.started_at


def create_submission(assessment_id: int, student_id: int, responses: dict[int, str],
                      marks: dict[int, tuple[Optional[int], Optional[str]]],
                      integrity_report: Optional[dict] = None) -> int:
    """responses: question_id -> answer text. marks: question_id -> (awarded or None, graded_by or None).
    The student's name and reference are taken from their account."""
    with _session() as s:
        a = s.get(Assessment, assessment_id)
        if a is None or a.status != "published":
            raise ValueError("This assessment is not accepting submissions.")
        st = s.get(Student, student_id)
        if st is None:
            raise ValueError("Student account not found.")
        sub = Submission(assessment_id=assessment_id, student_id=student_id,
                         student_name=st.name, student_ref=st.student_ref or "",
                         student_key=_student_key(st.name, st.student_ref or ""),
                         integrity_report=integrity_report)
        for q in a.questions:
            awarded, by = marks.get(q.id, (None, None))
            sub.answers.append(Answer(question_id=q.id, response=responses.get(q.id) or "",
                                      awarded=awarded, graded_by=by))
        s.add(sub)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise DuplicateError("A submission for this student already exists.")
        return sub.id


def list_submissions(assessment_id: int, teacher_id: int) -> list[dict]:
    """Teacher view: all submissions for one assessment."""
    with _session() as s:
        a = _owned(s, assessment_id, teacher_id)
        return [dict(id=sub.id, student_id=sub.student_id, student_name=sub.student_name,
                     student_ref=sub.student_ref, submitted_at=sub.submitted_at,
                     integrity_report=sub.integrity_report,
                     answers=[_answer_dict(x) for x in sub.answers])
                for sub in a.submissions]


def update_answer(answer_id: int, teacher_id: int, awarded: Optional[int], feedback: str, graded_by: str) -> None:
    with _session() as s:
        ans = s.get(Answer, answer_id)
        if ans is None:
            raise LookupError("Answer not found.")
        q = s.get(Question, ans.question_id)
        _owned(s, s.get(Submission, ans.submission_id).assessment_id, teacher_id)
        ans.awarded = None if awarded is None else max(0, min(q.marks, int(awarded)))
        ans.feedback = feedback or ""
        ans.graded_by = graded_by
        s.commit()


# ------------------------------------------------------------------ student activity
def _score_summary(sub: Submission) -> dict:
    out_of = sum(q.marks for q in sub.assessment.questions)
    got = sum(x.awarded for x in sub.answers if x.awarded is not None)
    pending = sum(1 for x in sub.answers if x.awarded is None)
    return dict(got=got, out_of=out_of, pending=pending)


def _released(sub: Submission) -> bool:
    """Results are visible to the student only when the teacher allows it (the assessment's show_score)."""
    return bool(sub.assessment.show_score)


def _student_submission_filter(st: Student):
    """A student's submissions: linked by id, or older ones made by name + reference."""
    return or_(Submission.student_id == st.id,
               Submission.student_key == _student_key(st.name, st.student_ref))


def list_student_submissions(student_id: int) -> list[dict]:
    """Everything a student has submitted, newest first.
    Keys: id, assessment_id, title, submitted_at, released, got, out_of, pending.
    Scores are None until the teacher releases results."""
    with _session() as s:
        st = s.get(Student, student_id)
        if st is None:
            return []
        subs = s.scalars(select(Submission).where(_student_submission_filter(st))
                         .order_by(Submission.submitted_at.desc(), Submission.id.desc())).all()
        out = []
        for sub in subs:
            released = _released(sub)
            summary = _score_summary(sub) if released else dict(got=None, out_of=None, pending=None)
            out.append(dict(id=sub.id, assessment_id=sub.assessment_id, title=sub.assessment.title,
                            submitted_at=sub.submitted_at, released=released, **summary))
        return out


def get_student_result(student_id: int, submission_id: int) -> Optional[dict]:
    """One submission for the student's results page. Returns None if it isn't this student's.
    Keys: id, title, released, answers, questions.
    When results are not released, answers and questions are empty so nothing leaks."""
    with _session() as s:
        st = s.get(Student, student_id)
        sub = s.get(Submission, submission_id)
        if st is None or sub is None:
            return None
        if sub.student_id != st.id and sub.student_key != _student_key(st.name, st.student_ref):
            return None
        released = _released(sub)
        return dict(id=sub.id, title=sub.assessment.title, submitted_at=sub.submitted_at,
                    released=released,
                    answers=[_answer_dict(x) for x in sub.answers] if released else [],
                    questions=[_question_dict(q) for q in sub.assessment.questions] if released else [])