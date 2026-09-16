# Time Tracking App

A time-tracking and task-management app: a Kanban board with swim lanes,
per-task timers, and an admin area — FastAPI backend, Next.js/React frontend.

## Structure

- `backend/` — FastAPI + SQLAlchemy API. See `backend/README.md` for setup,
  domain model, and the timer state machine spec.
- `frontend/` — Next.js (App Router) + TypeScript UI. See
  `frontend/README.md` for setup and structure.
- `.claude/agents/` — Claude Code subagents for this project's workflow:
  - `solution-architect` — system design, schema, API contracts; invoke
    first for any new feature.
  - `designer` — UI/UX for the board, swim lanes, task cards, timer
    controls, admin screens.
  - `backend-dev` — implements FastAPI endpoints/logic from the architect's
    design.
  - `qa` — tests features against spec, especially the timer state machine.

## Quickstart

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload   # http://localhost:8000

# Frontend (separate shell)
cd frontend
npm install
cp .env.example .env.local
npm run dev                      # http://localhost:3000
```

## Domain model

`User` — `Project` — `Task` (Kanban status: backlog/todo/in_progress/
in_review/done, assignable, ordered) — `TimeEntry` (one timer lifecycle per
task per user; state machine: `running <-> paused -> stopped`, at most one
active timer per user at a time). Full detail in `backend/README.md`.
