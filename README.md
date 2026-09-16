# Time Tracking App

An in-house Operations department app combining ClickUp-style task
management with Clockify-style time tracking — FastAPI backend, Next.js/React
frontend. Product scope and rules live in [`docs/PRD.md`](docs/PRD.md); this
is the source of truth for behavior, not this README.

## Structure

- `docs/PRD.md` — the product requirements document.
- `backend/` — FastAPI + SQLAlchemy API. See `backend/README.md` for setup,
  domain model, and the timer state machine spec.
- `frontend/` — Next.js (App Router) + TypeScript UI. See
  `frontend/README.md` for setup and structure.
- `.claude/agents/` — Claude Code subagents for this project's workflow, all
  grounded in `docs/PRD.md`:
  - `solution-architect` — system design, schema, API contracts; invoke
    first for any new feature.
  - `designer` — UI/UX for the board, swim lanes, task cards, timer
    controls, admin screens.
  - `backend-dev` — implements FastAPI endpoints/logic from the architect's
    design.
  - `qa` — tests features against the PRD, especially the timer state
    machine.

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

The first account you register becomes an admin, so you can immediately
configure the board's swim-lane grouping and custom fields from `/admin`.

## Deploying it live

See [`DEPLOY.md`](DEPLOY.md) — a `render.yaml` blueprint deploys the
backend, frontend, and a free Postgres database to Render in one click.

## Domain model

`User` (role + manager hierarchy) — `Project` (optional) — `Task` (type,
category, priority, the fixed 5-status Kanban workflow) — `TimeEntry` (the
timer state machine) — `TaskComment` / `TaskAuditEntry` — `TaskStatusEvent`
(reporting source of truth) — `CustomFieldDefinition` / `TaskCustomValue` —
`BoardConfig` (swim-lane grouping). Full detail, including the exact timer
rules, in `backend/README.md`.

## Reporting

Control chart, cycle time, lead time, throughput, and a cumulative flow
diagram are all served from `/reports/*` and rendered on the frontend's
`/reports` page.

## Notifications

`/notifications/reminders` computes which employees haven't logged time
recently (the PRD's compliance mechanism, since there's no approval step) —
delivering that as an actual email/Slack notification is a follow-up not
yet wired up.
