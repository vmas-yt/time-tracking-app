# Backend (FastAPI)

Implements the domain model and API described in [`../docs/PRD.md`](../docs/PRD.md).

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

API docs available at `http://localhost:8000/docs`. The very first
registered user becomes an admin (bootstrap), so there's someone able to
configure the board/custom fields/roles from a fresh database.

## Tests

```bash
DATABASE_URL=sqlite:///./time_tracking.db pytest
```

(The `DATABASE_URL` override keeps tests off whatever database the
environment configures for the real app — see "Database" below.)

## Domain model

- **User** — `role` is `employee`, `manager`, or `admin`; `manager_id`
  points to the user's line manager (used for review/reminder scoping).
- **Project** — optional grouping; tasks don't require one.
- **Task** — `task_type` (`normal`/`ad_hoc`), `category` (fixed set +
  `category_other_text` for "Others"), `priority` (`normal`/`expedite`),
  optional `project_id`/`assignee_id`, and the fixed 5-value `status`.
- **TimeEntry** — one timer lifecycle for a user working on a task.
- **TaskComment** — free-text comments on a task.
- **TaskAuditEntry** — human-readable audit trail (created/updated/status
  changes/comments/timer actions), visible to the task's own
  employee/manager/admin.
- **TaskStatusEvent** — structured status-change log; the source of truth
  for all reporting endpoints.
- **CustomFieldDefinition** / **TaskCustomValue** — admin-defined custom
  fields (ClickUp-style), applied per task.
- **BoardConfig** — singleton row controlling which field the Kanban board
  groups swim lanes by (`assignee`, `task_type`, `category`, or `priority`).

## Task status workflow (fixed, 5 values)

```
Backlog -> To Do -> In Progress -> On Hold -> Completed
   \_________________________/
     (Backlog -> On Hold directly is also valid)
```

`In Progress` and `Completed` are reached **only** through the timer
(start/resume, and stop respectively) — see `app/services/tasks.py`'s
`ALLOWED_MANUAL_TRANSITIONS` for every other transition, applied via
`PATCH /tasks/{id}`.

## Timer state machine

A `TimeEntry` moves through `RUNNING <-> PAUSED -> STOPPED` (terminal).
Combined with the task's status, per the PRD:

- **Start** (`POST /time-entries/start?task_id=`) only works when the task
  is `To Do` or `On Hold` *and* has no open (non-stopped) entry yet. Moves
  the task to `In Progress`.
- **Pause** (`POST /time-entries/{id}/pause`) stops the timer without
  touching the task's status.
- Moving a task to **On Hold manually** (`PATCH /tasks/{id}` with
  `status: on_hold`) auto-pauses its running timer.
- **Resume** (`POST /time-entries/{id}/resume`) on a task that's `On Hold`
  moves it straight to `In Progress` (never back through `To Do`); on a
  task that's still `In Progress` (paused via the Pause action) it leaves
  the status alone.
- **Stop** (`POST /time-entries/{id}/stop`) is terminal: the task becomes
  `Completed` and no further transition — manual or timer — is ever valid
  on it again.
- A user may have **at most one `RUNNING` entry** at a time, but any number
  of their tasks may sit `In Progress` (paused) or `On Hold` in parallel.

See `backend/tests/test_timer_state_machine.py` for the full behavior
contract, including every rejected transition.

## Authorization

- `services/authz.py` has two checks, applied consistently across every
  task-scoped read/write endpoint (not just comments/audit):
  - `assert_can_view_task` (read access) — the task's assignee, its creator,
    the assignee's line manager, or an admin. Used by `GET /tasks/{id}`,
    `GET/POST /tasks/{id}/comments`, and `GET /tasks/{id}/audit`.
  - `assert_can_edit_task` (write access) — the task's assignee, its
    creator, or an admin. Deliberately **excludes** the manager: per the
    PRD, managers review time/tasks, they don't edit a report's tasks or
    control their timer. Used by `PATCH`/`DELETE /tasks/{id}` and every
    `/time-entries/start|{id}/pause|{id}/resume|{id}/stop` endpoint (the
    latter checked against the entry's task, not just entry ownership, so a
    task reassigned mid-timer is still governed by its current owner).
  - `GET /tasks` additionally scopes its results for non-admins to tasks
    they can view — an employee's board never lists a peer's tasks.
- `GET /tasks?manager_id={id}` returns every task assigned to someone whose
  `manager_id` is `{id}` — the "my team" board a line manager needs in one
  call, instead of one `assignee_id` lookup per direct report.

## Data-loss guard on delete

`DELETE /tasks/{id}` returns **409** if the task has any `TimeEntry` rows,
instead of silently cascading the delete through its time entries, audit
trail, and status events (which would corrupt reporting numbers for a task
that had real work logged against it). Tasks with no logged time can still
be deleted outright — there's nothing to lose.

## Concurrency guard on the timer invariants

The two PRD invariants — "only one open (non-stopped) `TimeEntry` per task"
and "only one `RUNNING` entry per user" — are enforced twice:
1. Query-then-check in `app/services/timer.py` (`open_entry_for_task`,
   `running_entry_for_user`), which is what most requests hit and what
   produces the friendly 409 messages.
2. A DB-level partial unique index on `time_entries` (see
   `TimeEntry.__table_args__` in `app/models.py`) as a backstop, so two
   genuinely concurrent requests (double-click, two tabs) can't both slip
   past check #1 and insert/update into two open or two running rows. The
   routers catch the resulting `IntegrityError` and return 409 instead of
   crashing. See `backend/tests/test_timer_db_constraints.py`, which writes
   straight to the ORM (bypassing the app-level check) to prove the index
   itself rejects the conflicting row.

## Reporting

`GET /reports/{cycle-time,control-chart,lead-time,throughput,cumulative-flow}`
are all computed from `TaskStatusEvent` + `Task.first_in_progress_at`/
`completed_at` — no separate analytics store.

## Notifications

`GET /notifications/reminders?days=N` returns employees with no logged time
in the last N days (scoped to direct reports for a manager, everyone for an
admin, just themselves for an employee) — the data behind the PRD's
compliance reminder. **This only computes who needs a nudge; it does not
send anything.** Wiring it to an actual delivery channel (email/Slack/etc.)
is a follow-up that needs outbound-notification infrastructure and
credentials this scaffold doesn't have.

## Database

`DATABASE_URL` defaults to a local SQLite file but is read from the
environment first — in a deployment where a real database (e.g. Postgres)
is provisioned via `DATABASE_URL`, this app picks it up automatically with
no code changes (`psycopg2-binary` is already a dependency).
