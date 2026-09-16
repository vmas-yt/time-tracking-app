# Backend (FastAPI)

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

API docs available at `http://localhost:8000/docs`.

## Tests

```bash
pytest
```

## Domain model

- **User** — account with email/password auth (JWT bearer tokens).
- **Project** — a container for tasks.
- **Task** — belongs to a project, optionally assigned to a user, has a
  Kanban `status` (`backlog`, `todo`, `in_progress`, `in_review`, `done`)
  and a `position` for ordering within a column.
- **TimeEntry** — one timer lifecycle for a user working on a task. See the
  state machine below.

## Timer state machine

A `TimeEntry` moves through:

```
        start           pause           stop
(none) ------> RUNNING <------> PAUSED ------> STOPPED
                  |                               ^
                  '-------------- stop ------------'
```

- A user may have at most **one** non-stopped (`running` or `paused`) timer
  at a time, across all tasks (`POST /time-entries/start` returns `409` if
  one is already active).
- `pause` is only valid from `running`; `resume` only from `paused`; `stop`
  is valid from either and is terminal — no transition out of `stopped`.
- Elapsed time is tracked as `accumulated_seconds` (banked from completed
  running segments) plus the live segment since `last_resumed_at`, exposed
  as `elapsed_seconds` on every response.

See `backend/tests/test_timer_state_machine.py` for the behavior contract.
