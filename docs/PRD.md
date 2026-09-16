# Time Tracking & Task Management App — PRD

## Purpose
A standalone, in-house application for the Operations department, combining
ClickUp-style task management with Clockify-style time tracking. Built for
internal use only — not a commercial product.

## Primary Users
- **Employees**: create and manage their own tasks, track time against them.
- **Line Managers**: review team time spent on tasks (review only — no
  approval step in the workflow).

## Explicit Non-Goals
- No billing or invoicing functionality.
- No manager approval step (managers review, they don't approve/reject).
- No integrations with external systems.
- No automatic or idle-time tracking — all tracking is manually started/stopped.

## Task Model
- **Type field**: `Normal` or `Ad-hoc` (not separate entities — a single field
  on the task).
- **Category field** (applies to both Normal and Ad-hoc tasks): Production
  Issue, Urgent Request, Meeting, Support Ticket, Cyber Security Request,
  Platform Support, Infrastructure, Others (free text).
- **Title**: mandatory.
- **Description**: optional.
- **Project link**: optional — tasks can be standalone or linked to a project.
  Employees mostly create and start their own tasks without needing a project.
- **Comments**: required feature, visible per task.
- **Audit trail**: required — visible to the employee on their own entries.
- **Attachments**: good-to-have, not required for v1.

## Statuses (fixed set of 5)
`Backlog → To Do → In Progress → On Hold → Completed`

- A task can move from **Backlog directly to On Hold**, as well as to To Do.
- Status modeling follows the same approach already used on the Product
  Operation Reporting Next.js app.

## Timer Logic
- **Start**: only works from `To Do` or `On Hold`. Moves the task to
  `In Progress` automatically.
- **Pause**: stops the timer without changing the task's status.
- **On Hold (manual)**: moving a task to On Hold manually auto-pauses its timer.
- **Resume from On Hold**: goes directly to `In Progress` (not back through To Do).
- **Stop**: marks the task `Completed` permanently. Cannot be reopened —
  further work on the same subject becomes a new task.
- An employee can have **multiple tasks** In Progress or On Hold in parallel.
- Only **one timer can be actively running** per employee at any time.

## Kanban Board
- Swim lanes are **admin-definable** — likely grouped by team member as the
  main use case, but the grouping field itself should be configurable
  (e.g., team member, task type, or a priority/"Expedite" field).
- Admins can define a configurable Kanban workflow.
- Admins can add **custom fields** to tasks (ClickUp-style).

## Notifications
- Reminder notifications to employees who haven't logged time.
- Reminder notifications to their Line Manager — since there's no approval
  step enforcing compliance, this is the main compliance mechanism.

## Reporting (must-have)
- Control chart
- Cycle time
- Lead time
- Cumulative flow diagram
- Throughput

## Tech Stack
- Backend: FastAPI (Python)
- Frontend: Next.js / React
