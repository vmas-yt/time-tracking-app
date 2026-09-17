# Kanban Board + Timer — Design Document

Status: draft for UI prototype + backend-integration hand-off
Owner: solution architect
Source of truth: `docs/PRD.md`
Reviewed against: `backend/app/models.py`, `backend/app/schemas.py`,
`backend/app/services/tasks.py`, `backend/app/services/timer.py`,
`backend/app/routers/tasks.py`, `backend/app/routers/time_entries.py`,
`backend/app/routers/admin.py`, `backend/app/routers/reports.py`,
`backend/app/routers/users.py`, `backend/app/routers/projects.py`,
`backend/tests/test_timer_state_machine.py`

This document is a design artifact, not a changelog of what exists. Where the
current backend already matches the PRD, it's marked **CONFIRMED — no rework
needed**. Where it deviates, is ambiguous, or should be tightened before a
real UI is wired to it, it's marked **GAP** or **PROPOSED CHANGE** with a
concrete recommendation. Nothing here should be read as "already shipped and
correct" unless it carries the CONFIRMED tag.

---

## 1. Data model

### 1.1 Entities relevant to the board/timer

```
User (users)
  id, email, full_name, hashed_password, role[employee|manager|admin],
  manager_id -> users.id | null, created_at

Project (projects)                          [optional link target]
  id, name, description?, created_at

Task (tasks)
  id, project_id -> projects.id | null, assignee_id -> users.id | null,
  created_by_id -> users.id,
  title, description?,
  task_type[normal|ad_hoc], category[enum incl. "other"], category_other_text?,
  priority[normal|expedite],
  status[backlog|todo|in_progress|on_hold|completed], position (int),
  created_at, updated_at, completed_at?, first_in_progress_at?

TimeEntry (time_entries)                    [one row per Start..Stop lifecycle]
  id, task_id -> tasks.id, user_id -> users.id,
  status[running|paused|stopped],
  started_at, last_resumed_at?, accumulated_seconds (float), ended_at?

TaskComment (task_comments)
  id, task_id, author_id, body, created_at

TaskAuditEntry (task_audit_entries)         [human-readable log]
  id, task_id, actor_id, action[enum], detail (string), created_at

TaskStatusEvent (task_status_events)        [structured, reporting source of truth]
  id, task_id, from_status?, to_status, changed_by_id, occurred_at

CustomFieldDefinition (custom_field_definitions)   [admin-defined, global]
  id, name, field_type[text|number|select|date|boolean], options? (CSV), created_at

TaskCustomValue (task_custom_values)
  id, task_id, field_id -> custom_field_definitions.id, value (string)

BoardConfig (board_config)                  [singleton row, id="default"]
  id, swimlane_field[assignee|task_type|category|priority], updated_at
```

Relationships: `Task 1—N TimeEntry`, `Task 1—N TaskComment`,
`Task 1—N TaskAuditEntry`, `Task 1—N TaskStatusEvent`,
`Task 1—N TaskCustomValue —N—1 CustomFieldDefinition`, `User 1—N Task`
(as assignee and separately as creator), `User 1—N TimeEntry`.

### 1.2 Validation against the PRD

**CONFIRMED — no rework needed:**
- Task has a single `task_type` field (`normal`/`ad_hoc`), not separate
  entities — matches PRD "not separate entities — a single field."
- `category` enum covers all 7 named PRD categories plus a free-text
  `other` (`category_other_text`, enforced required-if-other by a Pydantic
  validator in `TaskBase`).
- `status` is the fixed 5-value enum (`backlog/todo/in_progress/on_hold/
  completed`) — no per-project or per-board custom status set exists, which
  matches the PRD's "fixed set of 5."
- `project_id` and `assignee_id` are nullable — tasks can be standalone,
  matching "Employees mostly create and start their own tasks without
  needing a project."
- Comments (`TaskComment`), audit trail (`TaskAuditEntry`), and the
  structured `TaskStatusEvent` log exist and are populated at every
  status/timer transition (see §3). This satisfies "Audit trail — required
  — visible to the employee on their own entries" and gives the reporting
  endpoints (`cycle-time`, `lead-time`, `throughput`, `cumulative-flow`,
  `control-chart`) a real source of truth.
- `BoardConfig.swimlane_field` and `CustomFieldDefinition` implement the
  admin-configurable swim-lane grouping and ClickUp-style custom fields.
- `TimeEntry` is correctly modeled as one row per Start→Stop lifecycle (not
  one row per pause/resume segment), with `accumulated_seconds` banking
  completed running segments and `last_resumed_at` marking the current
  segment's start. This is the right shape for "elapsed time so far" queries
  without needing a separate segments table.

**GAP — PRD ambiguity that the current design resolves silently; flagging
so it's an explicit decision, not an accident:**
- The PRD's "Statuses" section fixes 5 statuses, but the "Kanban Board"
  section separately says "Admins can define a configurable Kanban
  workflow." The backend resolves this tension by making the *status set*
  fixed (`TaskStatus` enum, not admin-editable) and only the *swim-lane
  grouping* (`BoardConfig.swimlane_field`) and *custom fields*
  admin-configurable. **Recommendation: keep this interpretation** — it
  matches the PRD's explicit 5-status list and the note that "status
  modeling follows the same approach already used on the Product Operation
  Reporting Next.js app." Call this out to the designer/PM as the
  interpretation being built to, in case "configurable workflow" was meant
  more literally (e.g., admins reordering/renaming columns). If that's
  wanted later, it's a new `BoardColumn` config table, not a change to
  `TaskStatus` itself (see §1.4).

**GAP — authorization is not enforced on the endpoints the board/timer will
actually call:**
- `services/authz.py` has `assert_can_view_task` (assignee, creator, or the
  assignee's manager, or an admin) and `assert_admin`, but they are only
  wired into the comments and audit-trail endpoints
  (`GET/POST /tasks/{id}/comments`, `GET /tasks/{id}/audit`). `GET /tasks`,
  `GET /tasks/{id}`, `PATCH /tasks/{id}`, `DELETE /tasks/{id}`, and every
  `/time-entries/*` endpoint currently have **no ownership or role check**
  beyond "is authenticated" — any logged-in user can read, edit, delete, or
  start/stop the timer on any other user's task. This conflicts with the
  PRD's user model ("Employees ... manage their own tasks"; "Line Managers:
  review ... no approval step") since managers should be read-only on
  others' tasks and employees shouldn't be able to mutate a peer's task.
  **Proposed fix (for backend-dev, not done here):** apply
  `assert_can_view_task` to the three read paths and add an
  `assert_can_edit_task` (assignee, creator, or admin — explicitly
  excluding manager) to `PATCH`/`DELETE /tasks/{id}` and all of
  `/time-entries/start|{id}/pause|{id}/resume|{id}/stop`. This is a
  breaking change for any client currently relying on the open access, but
  none should be, since there's no real UI yet.

**GAP — no concurrency guard at the DB layer for the two invariants the PRD
calls out ("only one RUNNING timer per user"; implicitly, at most one open
entry per task):**
- Both are currently enforced only by a query-then-insert check in the
  router (`open_entry_for_task`, `running_entry_for_user` in
  `services/timer.py`), with no unique index or transaction-level lock.
  Two concurrent `POST /time-entries/start` calls (e.g., double-click, or
  two browser tabs) can race past both checks and create two open entries.
  **Recommendation:** add a partial unique index —
  `UNIQUE(task_id) WHERE status != 'stopped'` and
  `UNIQUE(user_id) WHERE status = 'running'` (Postgres partial index syntax;
  SQLite equivalent via a filtered unique index or an app-level
  `SELECT ... FOR UPDATE` if the DB is swapped later) — and catch the
  resulting `IntegrityError` as a 409. Low priority for the prototype (dummy
  data, single user at a time) but should be fixed before this is exposed
  to real concurrent users.

**GAP — task deletion has no data-loss guard:**
- `DELETE /tasks/{id}` hard-deletes the task and cascades to its
  `TimeEntry`, `TaskComment`, `TaskAuditEntry`, and `TaskStatusEvent` rows
  (`cascade="all, delete-orphan"` in `models.py`). A task with logged time
  can be permanently deleted with no trace, which undermines the audit
  trail and reporting numbers (throughput/cycle-time would silently lose a
  completed task). **Recommendation:** either (a) block deletion when the
  task has any `TimeEntry` rows (return 409), or (b) replace hard delete
  with a soft-delete/archive flag and exclude archived tasks from the board
  and reports. Not a PRD requirement explicitly, but a correctness risk
  worth flagging before backend-dev builds on it.

**GAP — no "my team" filter for managers on the board:**
- `GET /tasks` supports `assignee_id` (single user) but the PRD's primary
  swim-lane use case is "grouped by team member" for a manager reviewing
  their team. There is no way to fetch "all tasks for everyone who reports
  to me" in one call — a manager's board would need N calls (one per
  direct report) or a client-side join against `GET /users`.
  **Proposed addition:** `GET /tasks?manager_id={id}` (join through
  `assignee.manager_id`), or a `mine_or_reports=true` convenience flag
  scoped to the current user. See §2 for the concrete shape. This is new,
  not a correction — flagging it as a proposed endpoint the designer should
  know is coming, so the prototype's manager view doesn't build against a
  fetch pattern the real API can't support.

### 1.3 Field-level notes for the UI

- `Task.position` is a single global integer, ordered within `status` only
  (`ORDER BY status, position` in `list_tasks`). It is **not** scoped per
  swim lane. This works fine for drag-and-drop as long as the frontend
  groups the already-sorted list into `(status, swimlane_value)` buckets
  client-side rather than expecting the API to pre-bucket it — confirmed
  workable, no change needed, but worth stating explicitly so the designer
  doesn't assume per-lane ordering from the API.
- `Task.first_in_progress_at` is set once, on the *first* transition into
  `in_progress` (i.e., first Start), and never overwritten by a later
  Resume. It is the anchor for cycle-time reporting. Note this does not
  subtract time spent On Hold — cycle time as currently computed is
  wall-clock from first Start to Stop, including any On-Hold pauses in
  between. That's a reasonable v1 definition but is a reporting nuance,
  not a board/timer concern; flagged here only because it lives on the
  `Task` row the board reads.
- `TimeEntry.elapsed_seconds` in `TimeEntryRead` is a **computed,
  non-persisted** field (`accumulated_seconds` plus the live segment if
  `status == running`) — the frontend should re-derive it client-side
  every tick (e.g., `accumulated_seconds + (now - last_resumed_at)` while
  running) rather than polling the API every second; the API value is only
  accurate as of the moment of the response.

### 1.4 If "configurable Kanban workflow" is later taken literally

Not being proposed now (see §1.2 GAP), but noting the shape so it isn't a
surprise: it would need a new `BoardColumn` table
(`id, status[maps to fixed TaskStatus enum], display_name, position,
is_visible`) rather than changing `TaskStatus` itself, since the timer
state machine (§3) is hard-wired to the 5 specific status values. Columns
could be renamed/reordered/hidden for display without touching the
underlying enum. Out of scope unless requested.

---

## 2. API contract

Base URL prefix per router: `/tasks`, `/time-entries`, `/admin`, `/users`,
`/projects`, `/auth`. All endpoints require `Authorization: Bearer <token>`
(`OAuth2PasswordBearer`, obtained from `POST /auth/login`) except login
itself. All list/detail responses below reflect exact Pydantic field names
from `backend/app/schemas.py`; enum values are the lowercase strings from
`backend/app/models.py`.

### 2.1 Tasks (board data)

**`GET /tasks`** — list tasks for the board.
- Query params: `project_id?`, `assignee_id?`, `status_filter?`
  (one of `backlog|todo|in_progress|on_hold|completed`).
- **PROPOSED ADDITION** (see §1.2): `manager_id?` — tasks whose assignee's
  `manager_id` equals this value, for a manager's team board.
- 200 → `TaskRead[]`, ordered by `(status, position)`.
- `TaskRead` shape:
  ```json
  {
    "id": "uuid", "title": "str", "description": "str|null",
    "project_id": "uuid|null", "assignee_id": "uuid|null",
    "task_type": "normal|ad_hoc",
    "category": "production_issue|urgent_request|meeting|support_ticket|cyber_security_request|platform_support|infrastructure|other",
    "category_other_text": "str|null",
    "priority": "normal|expedite",
    "created_by_id": "uuid",
    "status": "backlog|todo|in_progress|on_hold|completed",
    "position": 0,
    "created_at": "iso8601", "updated_at": "iso8601",
    "completed_at": "iso8601|null",
    "custom_values": { "<custom_field_id>": "str" }
  }
  ```
- 401 if unauthenticated.

**`POST /tasks`** — create a task. Always created in `backlog`; if
`assignee_id` omitted, defaults to the creator.
- Body: `TaskCreate` = `TaskRead` minus server-set fields (`title` required;
  `category` required, `category_other_text` required iff
  `category == "other"` — 422 otherwise via Pydantic validator).
- 201 → `TaskRead`. 422 on validation failure (missing title/category, or
  missing `category_other_text` for `other`).

**`GET /tasks/{id}`** — 200 → `TaskRead`; 404 if not found.
- **GAP:** currently no `assert_can_view_task` — see §1.2. Recommend 403
  for users outside {assignee, creator, assignee's manager, admin}.

**`PATCH /tasks/{id}`** — manual field/status edits. **Cannot** set
`status` to `in_progress` or `completed` — those are timer-only (see §3).
- Body: `TaskUpdate` — all fields optional: `title`, `description`,
  `assignee_id`, `category`, `category_other_text`, `priority`, `position`,
  `status` (must be a legal manual transition, §3), `custom_values`
  (`dict[field_id, value]`, upserted).
- 200 → `TaskRead`.
- 404 task not found.
- 409 illegal status transition (e.g., `backlog → in_progress` directly, or
  any transition out of `completed`) — detail message names the attempted
  from/to.
- 409 if attempting `on_hold → todo|backlog` while an open timer entry
  still exists on the task (must Resume-then-Stop or Stop first).
- 400 if `custom_values` references an unknown `field_id`.
- **GAP:** no `assert_can_edit_task` — see §1.2.

**`DELETE /tasks/{id}`** — 204; 404 if not found.
- **GAP:** hard-deletes all child rows (time entries, comments, audit,
  status events) with no guard — see §1.2 recommendation to block or
  soft-delete when time has been logged.

**`GET /tasks/{id}/comments`**, **`POST /tasks/{id}/comments`**
- GET → 200 `CommentRead[]` in creation order.
- POST body `{ "body": "str" }` → 201 `CommentRead`; also appends a
  `commented` audit entry (body truncated to 120 chars in the audit detail).
- Both currently gated by `assert_can_view_task` (403 if not
  assignee/creator/their manager/admin) — CONFIRMED correct as-is.

**`GET /tasks/{id}/audit`** — 200 → `AuditEntryRead[]` in chronological
order, action ∈ `created|updated|status_changed|commented|timer_started|
timer_paused|timer_resumed|timer_stopped`. Same `assert_can_view_task` gate.

### 2.2 Time entries (timer)

**`GET /time-entries?task_id=?`** — the current user's own entries
(newest first), optionally filtered to one task. 200 → `TimeEntryRead[]`.

**`GET /time-entries/open`** — the current user's non-`stopped` entries:
at most one `running`, plus any number of `paused` entries belonging to
other tasks sitting `in_progress` (paused) or `on_hold`. This is the
endpoint the board/header timer widget polls to know "what's running / what
else is paused for me." 200 → `TimeEntryRead[]`.

`TimeEntryRead` shape:
```json
{
  "id": "uuid", "task_id": "uuid", "user_id": "uuid",
  "status": "running|paused|stopped",
  "started_at": "iso8601",
  "last_resumed_at": "iso8601|null",
  "accumulated_seconds": 0.0,
  "ended_at": "iso8601|null",
  "elapsed_seconds": 0.0
}
```

**`POST /time-entries/start?task_id={id}`**
- 201 → `TimeEntryRead` (`status: "running"`). Side effects: task →
  `in_progress`; sets `first_in_progress_at` if unset; records one
  `status_changed` `TaskStatusEvent`/audit entry and one `timer_started`
  audit entry.
- 404 task not found.
- 409 task status is not `todo`/`on_hold`.
- 409 task already has an open (non-stopped) entry — use resume instead.
- 409 caller already has a `running` entry on a different task.

**`POST /time-entries/{id}/pause`**
- 200 → `TimeEntryRead` (`status: "paused"`). Task status **unchanged**.
  Audit: `timer_paused`.
- 404 entry not found or not owned by caller.
- 409 entry not currently `running`.

**`POST /time-entries/{id}/resume`**
- 200 → `TimeEntryRead` (`status: "running"`).
  - If task is `on_hold` → task moves to `in_progress` (records
    `status_changed` event/audit), matching "Resume from On Hold goes
    directly to In Progress."
  - If task is already `in_progress` (plain pause/resume case) → task
    status unchanged.
  - Audit: `timer_resumed`.
- 404 entry not found/not owned.
- 409 entry not currently `paused`.
- 409 caller has a different `running` entry elsewhere (only one RUNNING
  timer per user).
- 409 task is in some other status (defensive; shouldn't occur if only
  Start/Pause/Resume/manual-On-Hold ever created the entry).

**`POST /time-entries/{id}/stop`**
- 200 → `TimeEntryRead` (`status: "stopped"`, `ended_at` set). Task →
  `completed`, `completed_at` set. Terminal — no further action on this
  entry or task is possible. Audit: `status_changed` + `timer_stopped`.
- 404 entry not found/not owned.
- 409 entry already `stopped`.
- Works from either `running` or `paused` entry state (stopping a paused
  timer still completes the task — confirmed via
  `test_stop_from_on_hold_paused_entry_completes_task`).

### 2.3 Board config & custom fields (admin)

**`GET /admin/board-config`** → 200 `{ "swimlane_field": "assignee|task_type|category|priority", "updated_at": "iso8601" }`. Auto-creates the singleton row with `assignee` default if missing. No admin gate on GET (any authenticated user can read the current grouping — needed by the board itself).

**`PATCH /admin/board-config`** → body `{ "swimlane_field": "..." }`. 200 same shape. 403 if not admin.

**`GET /admin/custom-fields`** → 200 `CustomFieldRead[]`
(`{ id, name, field_type, options: string[]|null, created_at }`). No admin gate on GET (board needs field definitions to render columns).

**`POST /admin/custom-fields`** → 201 `CustomFieldRead`. 403 if not admin.

**`DELETE /admin/custom-fields/{id}`** → 204. 403 if not admin. 404 if not found. Note: does not cascade-clean `TaskCustomValue` rows referencing the deleted field — **minor GAP**, orphaned values would remain and `PATCH /tasks/{id}` custom-value lookups only fail on *unknown* fields going forward, not on stale ones; low priority for now since it doesn't block the board rendering (frontend just ignores values for field ids it doesn't recognize).

### 2.4 Supporting lookups the board needs

**`GET /users`** → `UserRead[]` (id, email, full_name, role, manager_id,
created_at) — for the assignee picker and for building "team member" swim
lanes client-side (group by `assignee_id`, label via this list).

**`GET /projects`** → `ProjectRead[]` — for the optional project filter/link.

---

## 3. Combined task-status + timer state machine

Two coupled state machines: `Task.status` (5 values) and `TimeEntry.status`
(`running|paused|stopped`, one row per lifecycle). A task's *current* open
entry (if any) is "the entry with `status != stopped`" — at most one may
exist per task at a time.

### 3.1 Manual status transitions (no timer involved)

| From | Action (PATCH /tasks/{id}, `status=...`) | To | Side effects | Error case |
|---|---|---|---|---|
| Backlog | set `todo` | To Do | status_changed event + audit | — |
| Backlog | set `on_hold` | On Hold | status_changed event + audit (no timer exists yet, nothing to pause) | — |
| To Do | set `backlog` | Backlog | status_changed event + audit | — |
| To Do | set `on_hold` | On Hold | status_changed event + audit; no running timer possible in `todo` so nothing to pause | — |
| On Hold | set `todo` | To Do | status_changed event + audit | **409** if the task has an open (non-stopped) entry — must Resume or Stop first |
| On Hold | set `backlog` | Backlog | status_changed event + audit | **409** same guard as above |
| In Progress | set `on_hold` | On Hold | Auto-pauses the running entry if one exists (`timer_paused` audit) **before** recording the status change; then status_changed event + audit | none — always allowed from In Progress |
| In Progress | set `todo`/`backlog`/`completed` | — | — | **409** not a legal manual transition (must go through timer, or through On Hold first) |
| Completed | any | — | — | **409** — terminal, no manual transition out |
| any | set `in_progress` | — | — | **409** — In Progress is timer-only, never a manual PATCH target |

### 3.2 Timer-driven transitions

| From (Task, TimeEntry) | Action | To (Task, TimeEntry) | Side effects | Error case |
|---|---|---|---|---|
| Task=To Do, no open entry | `POST /time-entries/start` | Task=In Progress, Entry=Running | New `TimeEntry` row (`started_at=last_resumed_at=now`, `accumulated_seconds=0`); sets `first_in_progress_at` if null; `status_changed` event/audit + `timer_started` audit | — |
| Task=On Hold, no open entry | `POST /time-entries/start` | Task=In Progress, Entry=Running (new entry) | Same as above — PRD: "Start ... only works from To Do or On Hold," treated as a fresh timer since no entry survived the manual On Hold that got here without ever starting | — |
| Task=Backlog | `POST /time-entries/start` | — | — | **409** — Start not allowed from Backlog |
| Task=In Progress or Completed | `POST /time-entries/start` | — | — | **409** — Start only from To Do/On Hold |
| Task has an existing open (running/paused) entry | `POST /time-entries/start` (any task status) | — | — | **409** — "already has an open timer; use resume instead" |
| Caller already has a different `running` entry (any task) | `POST /time-entries/start` | — | — | **409** — only one RUNNING timer per user |
| Entry=Running | `POST /time-entries/{id}/pause` | Task unchanged, Entry=Paused | Banks elapsed segment into `accumulated_seconds`, clears `last_resumed_at`; `timer_paused` audit | — |
| Entry=Paused or Stopped | `POST /time-entries/{id}/pause` | — | — | **409** — can only pause a Running entry |
| Entry=Paused, Task=In Progress (plain pause, not On Hold) | `POST /time-entries/{id}/resume` | Task stays In Progress, Entry=Running | Sets `last_resumed_at=now`; `timer_resumed` audit only (no status_changed) | — |
| Entry=Paused, Task=On Hold | `POST /time-entries/{id}/resume` | Task=In Progress, Entry=Running | `status_changed` event/audit (`on_hold → in_progress`) then `timer_resumed` audit | — |
| Entry=Running or Stopped | `POST /time-entries/{id}/resume` | — | — | **409** — can only resume a Paused entry |
| Caller has a different `running` entry elsewhere | `POST /time-entries/{id}/resume` | — | — | **409** — only one RUNNING timer per user |
| Task somehow not In Progress/On Hold when resuming (defensive) | `POST /time-entries/{id}/resume` | — | — | **409** |
| Entry=Running or Paused, any open task status | `POST /time-entries/{id}/stop` | Task=Completed (terminal), Entry=Stopped | Banks final running segment if was Running; sets `ended_at`; `completed_at` set on task; `status_changed` event/audit + `timer_stopped` audit | — |
| Entry=Stopped | `POST /time-entries/{id}/stop` | — | — | **409** — already stopped |
| Task=Completed, any entry | `pause`/`resume`/`stop` on that entry | — | — | **409** on all three — terminal, no reopening (per `test_stop_marks_task_completed_permanently`) |
| Task=Completed | `PATCH /tasks/{id}` any status | — | — | **409** — terminal |

### 3.3 Parallelism invariants (explicit, since they're easy to get wrong in UI state)

- A user may have **many** tasks simultaneously in `In Progress` (paused)
  or `On Hold` — each with its own open `TimeEntry` in `paused` state.
- A user may have **at most one** `TimeEntry` in `running` state at any
  time, across all their tasks. Starting/resuming a second one is rejected
  (409) until the first is paused or stopped.
- Pausing one task's timer immediately frees the user to Start or Resume a
  different task (confirmed by
  `test_pausing_one_task_frees_up_starting_another`).
- A task has **at most one open entry** (running or paused) at a time; once
  that entry is `stopped`, the task is `completed` and no new entry can
  ever be created for it (Start requires To Do/On Hold, which a completed
  task can never re-enter).

### 3.4 Audit trail ordering (confirmed correct)

For a full Start → Pause → Resume → Stop cycle, `GET /tasks/{id}/audit`
returns, in order: `created`, `status_changed` (creation's implicit
Backlog event is via `TaskStatusEvent`, not audit — audit's first two
entries in the existing test are `created` then the manual `backlog→todo`
`status_changed` done as setup), `status_changed` (`todo→in_progress`),
`timer_started`, `timer_paused`, `timer_resumed`, `status_changed`
(`→completed`), `timer_stopped` — i.e., every status change gets its own
`status_changed` audit entry **in addition to** the paired `timer_*` entry,
and both are backed by a `TaskStatusEvent` row for reporting. CONFIRMED via
`test_audit_trail_records_lifecycle`.

---

## 4. Summary for hand-off

**For the designer (frontend, dummy data now):** build the Kanban board
against `TaskRead` (§2.1) grouped by `BoardConfigRead.swimlane_field`
(assignee/task_type/category/priority) into the 5 fixed status columns;
build the timer widget against `TimeEntryRead` + `/time-entries/open`
(§2.2), rendering "Start" only when a task is `todo`/`on_hold` with no
open entry, "Pause"/"Stop" only on the entry that's currently `running`,
and "Resume" on any of the user's `paused` entries — enforcing client-side
that only one entry can show a live-ticking "running" state at a time.
Comments/audit panels consume `CommentRead`/`AuditEntryRead` (§2.1). Use
the exact enum string values in §1/§2 for dummy data so no relabeling is
needed when real data arrives.

**For backend-dev (later, real integration):** the endpoints, request/
response shapes, and transition rules in §2–§3 are implementation-ready as
documented for everything marked CONFIRMED. Before wiring a real UI to it,
address the GAPs in §1.2 in priority order: (1) ownership/role enforcement
on task read/write and all timer endpoints, (2) a manager-scoped task list
filter, (3) a delete guard on tasks with logged time, (4) a DB-level unique
guard against the two open-timer race conditions. None of these change the
shapes in §2 or the transition table in §3 — they only add 403/409 cases
and one new query param, so the prototype can be built now without
rework later.
