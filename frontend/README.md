# Frontend (Next.js)

## Setup

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Runs at `http://localhost:3000`. Requires the backend running at the URL in
`NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).

## Structure

- `src/app/` — routes:
  - `/` — project list
  - `/login` — register/log in
  - `/board?project=<id>` — Kanban board (project filter optional; tasks
    are standalone by default per the PRD)
  - `/tasks/[id]` — task detail: description, timer, comments, audit trail
  - `/admin` — swim-lane grouping, custom fields, user role/manager
    assignment
  - `/reports` — control chart, cycle time, lead time, throughput,
    cumulative flow diagram
- `src/app/board/` — the board's own UI: `BoardScreen`, `SwimLane`,
  `TaskCard`, `TimerControls`, `TaskDetailPanel` (slide-over), `Toast`,
  `NewTaskForm`. `TimerControls` and `Toast` take their state as props
  rather than reading a specific context, so `/tasks/[id]` reuses them
  directly instead of duplicating timer/toast UI.
- `src/board/` — the board's real, API-backed logic (no dummy data):
  - `engine.ts` — pure guard functions mirroring
    `docs/design/kanban-timer-design.md` §3 (`canStart`, `canResume`,
    `canManualMove`, `canEditTask`, `validDropTargets`, elapsed-time
    re-derivation). These are UI-only "should this control be
    shown/enabled" checks; the backend re-validates every mutation and is
    the actual source of truth.
  - `lanes.ts` — groups a task list into swim lanes for whichever
    `BoardConfig.swimlane_field` is active.
  - `format.ts` — duration/relative-time formatting.
  - `session.ts` — `useTimerSession()`, the hook both the board and the
    standalone task detail page use for "who am I, what timers of mine are
    open, can I edit this task," plus `start`/`pause`/`resume`/`stop`
    wired to the real timer endpoints with per-task pending state and a
    toast on any failure (see below). Also exports `useCompletedEntry` for
    showing a completed task's logged duration when the viewer is its
    timer owner.
  - `store.tsx` — `BoardProvider`/`useBoard()`, composing `session.ts` with
    the board's task/user/board-config fetching, `move`, `createTask`, and
    `setSwimlaneField`.
- `src/components/` — `NavBar` plus the shared design-system primitives in
  `src/components/ui/` (`Button`, `Card`, `Badge`, `Input`, `Select`). Build
  new UI out of these rather than hand-rolling styles.
- `src/lib/api.ts` — thin fetch wrapper against the FastAPI backend, JWT
  stored in `localStorage`. Throws `ApiError` (message + HTTP status) on any
  non-2xx response.
- `src/lib/types.ts` — mirrors the backend's Pydantic schemas
  (`backend/app/schemas.py`).

The Kanban board has 5 fixed columns (`backlog`, `todo`, `in_progress`,
`on_hold`, `completed`) and swim lanes grouped by whatever field the admin
picked (team member, task type, category, or priority). Dragging a card
only works for the manually-reachable columns (`backlog`/`todo`/`on_hold`)
and only if the viewer is the task's assignee/creator/an admin —
`in_progress`/`completed` are timer-only, and a task you can only view
(e.g. a manager reviewing a report's task) isn't draggable, since the
backend would 403 on the drop anyway. Each task card has inline timer
controls that only ever offer actions valid for that task's current state.

### Authorization surfaced in the UI

Per the backend's ownership/race-condition hardening
(`backend/app/services/authz.py`, `backend/app/routers/time_entries.py`):

- Tasks you can only *view* (not edit) — e.g. a line manager looking at a
  direct report's task — render a read-only "Only the assignee can control
  this timer" label instead of Start/Pause/Resume/Stop buttons, and the
  card isn't draggable. This avoids inviting an action the backend would
  reject with 403.
- Any 403 (not authorized) or 409 (illegal transition, already-open timer,
  or a genuine start/resume race caught by the backend's DB-level unique
  constraint) from a task or timer mutation surfaces as a dismissible toast
  with the backend's own message — never a silent no-op or a crashed page.
- `DELETE /tasks/{id}` returning 409 (task has logged time) is likewise
  meant to surface as a visible error wherever task deletion is wired up in
  the UI; there's no delete action on the board itself today.
- `GET /tasks` is filtered server-side to what the current user may view
  (assignee, creator, or their reports' manager) for non-admins — the board
  doesn't do any additional client-side filtering on top of that. An admin
  can narrow the board to one manager's team via the "Team" selector, which
  uses `GET /tasks?manager_id=`.

## Design system

Follows the **Wise-Inspired-design-analysis** system documented in
`/DESIGN.md` (the project has several named design analyses in that file;
this app implements that one specifically). Tailwind CSS v4 (CSS-first
config — see the `@theme` block in `src/app/globals.css`, where every token
name mirrors `DESIGN.md`'s `{colors.*}` names) plus a small set of
hand-built primitives in `src/components/ui/` (`Button`, `Card`, `Badge`,
`Input`, `Select`).

Signature traits: a lime-green `primary` CTA accent (`#9fe870`, text
`on-primary` near-black) used sparingly for primary actions and the active
nav tab; a sage-tinted `canvas-soft` page background with white `canvas`
cards — surface contrast *is* the elevation, so cards carry no border or
shadow; `rounded-xl` (24px) as the canonical card/button radius; Inter as
the typeface, bold headings approximating Wise Sans' heavy display weight.
Charts on `/reports` are colored from Wise's semantic + accent tokens
(`positive`, `accent-cyan`, `warning-deep`, `negative`, `ink-deep`).

Redesigning to a different named analysis in `DESIGN.md` means re-deriving
`globals.css`'s `@theme` tokens and the `ui/` primitives from that
analysis's `colors`/`typography`/`spacing`/`rounded`/`components` blocks —
the rest of the app (board, pages, etc.) consumes those primitives and
shouldn't need to change.

## Known follow-ups

- `npm audit` reports moderate/high advisories in `postcss`, a build-time
  transitive dependency of Next.js with no runtime exposure in this app.
  Clearing them requires the Next.js 16 major upgrade (React 19); left for
  a deliberate follow-up rather than bundled into this scaffold.
- No cross-tab/cross-user live sync: the board refetches tasks and open
  timers after your own mutations, but doesn't poll, so a teammate
  starting/stopping a timer or moving a card elsewhere won't appear until
  you next reload or act. Acceptable for the PRD's scale; a polling or
  websocket layer would be a follow-up if it becomes a real pain point.
- A completed task's logged duration is only shown to its own timer owner
  (`GET /time-entries` is scoped server-side to the caller's own entries —
  see `docs/design/kanban-timer-design.md` §2.2); anyone else viewing a
  completed task (e.g. a manager) sees a plain "Completed" pill with no
  duration. Showing it to viewers too would need a backend change (e.g. an
  aggregate "total logged time" field on `TaskRead`), flagged here rather
  than invented client-side.
