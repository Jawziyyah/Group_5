# Exam Platform (prototype)

Teachers log in, generate questions from a document with Gemini, edit them, publish an assessment with a
class code, and see students' submissions and scores. Students enter the code and answer - no account needed.

## Run locally
    pip install -r requirements.txt
    streamlit run app.py

Data is saved in `exam_platform.db` (SQLite) next to the app.

## Deploy (Streamlit Community Cloud)
Main file: `app.py`. In App settings -> Secrets add (see `.streamlit/secrets.toml.example`):
- `DATABASE_URL` - a Postgres URL (Supabase/Neon). Without it, data is wiped whenever the app restarts.
- `TEACHER_INVITE_CODE` - only people with this code can create a teacher account.
- `GEMINI_API_KEY` - optional. If omitted, each teacher pastes their own key in the sidebar.

## Files
- `app.py` - navigation and sidebar
- `views/` - login, create/edit/publish, my assessments (submissions and scores), take an assessment
- `db.py` - database models and queries
- `quiz_engine.py` - question generation, fact-checking, marking
- `editor_model.py`, `grading.py`, `auth.py` - editor logic, marking helpers, password hashing
