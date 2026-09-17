import type {
  AuditEntry,
  BoardConfig,
  Comment,
  Task,
  TimeEntry,
  User,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Dummy-data prototype for the Kanban board + timer feature.
// Field names/enum values mirror `docs/design/kanban-timer-design.md` §1–§2
// exactly, so nothing needs relabeling when this is wired to the real API.
// Everything below is generated once per page load, in memory only.
// ---------------------------------------------------------------------------

const NOW = Date.now();
const minutesAgo = (n: number) => new Date(NOW - n * 60_000).toISOString();
const hoursAgo = (n: number) => minutesAgo(n * 60);
const daysAgo = (n: number) => hoursAgo(n * 24);

export const USERS: User[] = [
  {
    id: "u1",
    email: "amara.osei@example.com",
    full_name: "Amara Osei",
    role: "employee",
    manager_id: "u4",
    created_at: daysAgo(220),
  },
  {
    id: "u2",
    email: "ben.whitfield@example.com",
    full_name: "Ben Whitfield",
    role: "employee",
    manager_id: "u4",
    created_at: daysAgo(180),
  },
  {
    id: "u3",
    email: "chidi.nwosu@example.com",
    full_name: "Chidi Nwosu",
    role: "employee",
    manager_id: "u4",
    created_at: daysAgo(150),
  },
  {
    id: "u4",
    email: "dana.kowalski@example.com",
    full_name: "Dana Kowalski",
    role: "manager",
    manager_id: null,
    created_at: daysAgo(400),
  },
];

// The single, implicit "current user" this whole prototype is viewed as —
// timer actions always act on this user's own entries, matching the design
// doc's "only one RUNNING timer per employee" invariant.
export const CURRENT_USER_ID = "u1";

function task(partial: Omit<Task, "custom_values" | "description" | "category_other_text"> & {
  description?: string | null;
  category_other_text?: string | null;
}): Task {
  return {
    description: null,
    category_other_text: null,
    custom_values: {},
    ...partial,
  };
}

export const TASKS: Task[] = [
  // ---- Backlog ---------------------------------------------------------
  task({
    id: "t1",
    project_id: null,
    assignee_id: "u2",
    created_by_id: "u4",
    title: "Rotate VPN certificates for satellite offices",
    description: "Certs for the two regional offices expire next month — rotate ahead of the deadline.",
    task_type: "normal",
    category: "infrastructure",
    priority: "normal",
    status: "backlog",
    position: 0,
    created_at: daysAgo(6),
    updated_at: daysAgo(6),
    completed_at: null,
  }),
  task({
    id: "t2",
    project_id: null,
    assignee_id: "u3",
    created_by_id: "u3",
    title: "Draft Q4 access-review checklist",
    description: "Needs sign-off criteria for each system before it can go to the wider team.",
    task_type: "ad_hoc",
    category: "other",
    category_other_text: "Compliance documentation",
    priority: "normal",
    status: "backlog",
    position: 1,
    created_at: daysAgo(4),
    updated_at: daysAgo(4),
    completed_at: null,
  }),
  task({
    id: "t3",
    project_id: null,
    assignee_id: "u1",
    created_by_id: "u1",
    title: "Evaluate new ticketing macros for support team",
    task_type: "normal",
    category: "support_ticket",
    priority: "normal",
    status: "backlog",
    position: 2,
    created_at: daysAgo(3),
    updated_at: daysAgo(3),
    completed_at: null,
  }),

  // ---- To Do -------------------------------------------------------------
  task({
    id: "t4",
    project_id: null,
    assignee_id: "u1",
    created_by_id: "u4",
    title: "Patch staging load balancer config",
    description: "Rollback plan required before touching production.",
    task_type: "normal",
    category: "infrastructure",
    priority: "expedite",
    status: "todo",
    position: 0,
    created_at: daysAgo(5),
    updated_at: daysAgo(1),
    completed_at: null,
  }),
  task({
    id: "t5",
    project_id: null,
    assignee_id: "u4",
    created_by_id: "u4",
    title: "Prep town hall slides for Ops sync",
    task_type: "normal",
    category: "meeting",
    priority: "normal",
    status: "todo",
    position: 1,
    created_at: daysAgo(2),
    updated_at: daysAgo(2),
    completed_at: null,
  }),
  task({
    id: "t6",
    project_id: null,
    assignee_id: "u2",
    created_by_id: "u2",
    title: "Reset locked accounts for finance team",
    task_type: "ad_hoc",
    category: "cyber_security_request",
    priority: "expedite",
    status: "todo",
    position: 2,
    created_at: hoursAgo(6),
    updated_at: hoursAgo(6),
    completed_at: null,
  }),

  // ---- In Progress ---------------------------------------------------------
  task({
    id: "t7",
    project_id: null,
    assignee_id: "u1",
    created_by_id: "u1",
    title: "Investigate checkout latency spike",
    description: "P1 reported by the storefront team at 09:40 — customers seeing 8s+ page loads.",
    task_type: "ad_hoc",
    category: "production_issue",
    priority: "expedite",
    status: "in_progress",
    position: 0,
    created_at: hoursAgo(3),
    updated_at: minutesAgo(9),
    completed_at: null,
  }),
  task({
    id: "t8",
    project_id: null,
    assignee_id: "u1",
    created_by_id: "u1",
    title: "Migrate legacy reports to new schema",
    task_type: "normal",
    category: "platform_support",
    priority: "normal",
    status: "in_progress",
    position: 1,
    created_at: daysAgo(2),
    updated_at: hoursAgo(3),
    completed_at: null,
  }),
  task({
    id: "t9",
    project_id: null,
    assignee_id: "u3",
    created_by_id: "u4",
    title: "Weekly vendor sync notes cleanup",
    task_type: "normal",
    category: "meeting",
    priority: "normal",
    status: "in_progress",
    position: 2,
    created_at: daysAgo(1),
    updated_at: hoursAgo(1.5),
    completed_at: null,
  }),

  // ---- On Hold ---------------------------------------------------------
  task({
    id: "t10",
    project_id: null,
    assignee_id: "u2",
    created_by_id: "u2",
    title: "Coordinate with vendor on outage RCA",
    description: "Blocked on the vendor's incident report — expected Thursday.",
    task_type: "normal",
    category: "production_issue",
    priority: "expedite",
    status: "on_hold",
    position: 0,
    created_at: daysAgo(3),
    updated_at: daysAgo(1),
    completed_at: null,
  }),
  task({
    id: "t11",
    project_id: null,
    assignee_id: "u3",
    created_by_id: "u3",
    title: "Refresh onboarding runbook",
    task_type: "normal",
    category: "platform_support",
    priority: "normal",
    status: "on_hold",
    position: 1,
    created_at: daysAgo(9),
    updated_at: hoursAgo(5),
    completed_at: null,
  }),
  task({
    id: "t12",
    project_id: null,
    assignee_id: "u1",
    created_by_id: "u1",
    title: "Review firewall rule exceptions",
    task_type: "normal",
    category: "cyber_security_request",
    priority: "normal",
    status: "on_hold",
    position: 2,
    created_at: daysAgo(2),
    updated_at: hoursAgo(2),
    completed_at: null,
  }),

  // ---- Completed ---------------------------------------------------------
  task({
    id: "t13",
    project_id: null,
    assignee_id: "u1",
    created_by_id: "u1",
    title: "Restore backup for HR shared drive",
    task_type: "ad_hoc",
    category: "infrastructure",
    priority: "expedite",
    status: "completed",
    position: 0,
    created_at: daysAgo(3),
    updated_at: daysAgo(2),
    completed_at: daysAgo(2),
  }),
  task({
    id: "t14",
    project_id: null,
    assignee_id: "u4",
    created_by_id: "u4",
    title: "Support ticket triage — August batch",
    task_type: "normal",
    category: "support_ticket",
    priority: "normal",
    status: "completed",
    position: 1,
    created_at: daysAgo(10),
    updated_at: daysAgo(7),
    completed_at: daysAgo(7),
  }),
  task({
    id: "t15",
    project_id: null,
    assignee_id: "u2",
    created_by_id: "u2",
    title: "Urgent request: exec travel access",
    task_type: "ad_hoc",
    category: "urgent_request",
    priority: "expedite",
    status: "completed",
    position: 2,
    created_at: daysAgo(4),
    updated_at: daysAgo(4),
    completed_at: daysAgo(4),
  }),
];

// ---------------------------------------------------------------------------
// Time entries — every entry, running/paused/stopped, belongs to the current
// user (CURRENT_USER_ID). Exactly one is `running` at a time, matching the
// parallelism invariants in §3.3 of the design doc.
// ---------------------------------------------------------------------------
export const TIME_ENTRIES: TimeEntry[] = [
  {
    id: "e1",
    task_id: "t7",
    user_id: CURRENT_USER_ID,
    status: "running",
    started_at: minutesAgo(14),
    last_resumed_at: minutesAgo(9),
    accumulated_seconds: 5 * 60,
    ended_at: null,
    elapsed_seconds: 0, // recomputed client-side every tick
  },
  {
    id: "e2",
    task_id: "t8",
    user_id: CURRENT_USER_ID,
    status: "paused",
    started_at: hoursAgo(3),
    last_resumed_at: null,
    accumulated_seconds: 42 * 60,
    ended_at: null,
    elapsed_seconds: 42 * 60,
  },
  {
    id: "e3",
    task_id: "t9",
    user_id: CURRENT_USER_ID,
    status: "paused",
    started_at: hoursAgo(1.5),
    last_resumed_at: null,
    accumulated_seconds: 18 * 60,
    ended_at: null,
    elapsed_seconds: 18 * 60,
  },
  {
    id: "e4",
    task_id: "t10",
    user_id: CURRENT_USER_ID,
    status: "paused",
    started_at: daysAgo(1),
    last_resumed_at: null,
    accumulated_seconds: 65 * 60,
    ended_at: null,
    elapsed_seconds: 65 * 60,
  },
  {
    id: "e5",
    task_id: "t11",
    user_id: CURRENT_USER_ID,
    status: "paused",
    started_at: hoursAgo(5),
    last_resumed_at: null,
    accumulated_seconds: 22 * 60,
    ended_at: null,
    elapsed_seconds: 22 * 60,
  },
  {
    id: "e6",
    task_id: "t12",
    user_id: CURRENT_USER_ID,
    status: "paused",
    started_at: hoursAgo(2),
    last_resumed_at: null,
    accumulated_seconds: 8 * 60,
    ended_at: null,
    elapsed_seconds: 8 * 60,
  },
  {
    id: "e7",
    task_id: "t13",
    user_id: CURRENT_USER_ID,
    status: "stopped",
    started_at: daysAgo(3),
    last_resumed_at: null,
    accumulated_seconds: 95 * 60,
    ended_at: daysAgo(2),
    elapsed_seconds: 95 * 60,
  },
  {
    id: "e8",
    task_id: "t14",
    user_id: CURRENT_USER_ID,
    status: "stopped",
    started_at: daysAgo(10),
    last_resumed_at: null,
    accumulated_seconds: 130 * 60,
    ended_at: daysAgo(7),
    elapsed_seconds: 130 * 60,
  },
  {
    id: "e9",
    task_id: "t15",
    user_id: CURRENT_USER_ID,
    status: "stopped",
    started_at: daysAgo(4),
    last_resumed_at: null,
    accumulated_seconds: 40 * 60,
    ended_at: daysAgo(4),
    elapsed_seconds: 40 * 60,
  },
];

export const COMMENTS: Comment[] = [
  {
    id: "c1",
    task_id: "t7",
    author_id: "u4",
    body: "Storefront team is pinging every 20 minutes — any update we can share?",
    created_at: minutesAgo(20),
  },
  {
    id: "c2",
    task_id: "t7",
    author_id: "u1",
    body: "Narrowed it to the checkout service's DB connection pool — digging into pool sizing now.",
    created_at: minutesAgo(11),
  },
  {
    id: "c3",
    task_id: "t8",
    author_id: "u3",
    body: "Heads up, the old `reports_v1` table has a few rows with null project_id — worth a sanity check post-migration.",
    created_at: hoursAgo(2),
  },
  {
    id: "c4",
    task_id: "t10",
    author_id: "u2",
    body: "Vendor confirmed they'll have the RCA over by Thursday EOD.",
    created_at: hoursAgo(20),
  },
  {
    id: "c5",
    task_id: "t13",
    author_id: "u4",
    body: "Confirmed restore looks good from HR's side, thanks for the quick turnaround.",
    created_at: daysAgo(2),
  },
];

function auditEntry(
  id: string,
  taskId: string,
  actorId: string,
  action: AuditEntry["action"],
  detail: string,
  createdAt: string
): AuditEntry {
  return { id, task_id: taskId, actor_id: actorId, action, detail, created_at: createdAt };
}

// Hand-authored per-task audit history seeded to match each task's current
// resting state (see docs/design/kanban-timer-design.md §3.4 for the real
// ordering rules this mirrors: status_changed before the paired timer_*
// entry for Start/Resume, timer_paused before status_changed for an
// in-progress -> on-hold auto-pause).
export const AUDIT_ENTRIES: AuditEntry[] = [
  // Backlog tasks — just created.
  auditEntry("a1", "t1", "u4", "created", "Created task", daysAgo(6)),
  auditEntry("a2", "t2", "u3", "created", "Created task", daysAgo(4)),
  auditEntry("a3", "t3", "u1", "created", "Created task", daysAgo(3)),

  // To Do tasks — created, then manually moved out of Backlog.
  auditEntry("a4", "t4", "u4", "created", "Created task", daysAgo(5)),
  auditEntry("a5", "t4", "u4", "status_changed", "Backlog → To Do", daysAgo(1)),
  auditEntry("a6", "t5", "u4", "created", "Created task", daysAgo(2)),
  auditEntry("a7", "t5", "u4", "status_changed", "Backlog → To Do", daysAgo(2)),
  auditEntry("a8", "t6", "u2", "created", "Created task", hoursAgo(6)),
  auditEntry("a9", "t6", "u2", "status_changed", "Backlog → To Do", hoursAgo(6)),

  // In Progress tasks — Start moves Backlog/To Do -> In Progress directly
  // via the timer (status_changed + timer_started paired).
  auditEntry("a10", "t7", "u1", "created", "Created task", hoursAgo(3)),
  auditEntry("a11", "t7", "u1", "status_changed", "To Do → In Progress", minutesAgo(14)),
  auditEntry("a12", "t7", "u1", "timer_started", "Started timer", minutesAgo(14)),
  auditEntry("a13", "t8", "u1", "created", "Created task", daysAgo(2)),
  auditEntry("a14", "t8", "u1", "status_changed", "To Do → In Progress", hoursAgo(3)),
  auditEntry("a15", "t8", "u1", "timer_started", "Started timer", hoursAgo(3)),
  auditEntry("a16", "t8", "u1", "timer_paused", "Paused timer", hoursAgo(0.3)),
  auditEntry("a17", "t9", "u4", "created", "Created task", daysAgo(1)),
  auditEntry("a18", "t9", "u3", "status_changed", "To Do → In Progress", hoursAgo(1.5)),
  auditEntry("a19", "t9", "u3", "timer_started", "Started timer", hoursAgo(1.5)),
  auditEntry("a20", "t9", "u3", "timer_paused", "Paused timer", hoursAgo(0.6)),

  // On Hold tasks — reached via In Progress, timer auto-paused before the
  // status change, per the manual-transition table.
  auditEntry("a21", "t10", "u2", "created", "Created task", daysAgo(3)),
  auditEntry("a22", "t10", "u2", "status_changed", "To Do → In Progress", daysAgo(1)),
  auditEntry("a23", "t10", "u2", "timer_started", "Started timer", daysAgo(1)),
  auditEntry("a24", "t10", "u2", "timer_paused", "Paused timer (auto — moved to On Hold)", hoursAgo(20)),
  auditEntry("a25", "t10", "u2", "status_changed", "In Progress → On Hold", hoursAgo(20)),
  auditEntry("a26", "t11", "u3", "created", "Created task", daysAgo(9)),
  auditEntry("a27", "t11", "u3", "status_changed", "To Do → In Progress", daysAgo(1)),
  auditEntry("a28", "t11", "u3", "timer_started", "Started timer", daysAgo(1)),
  auditEntry("a29", "t11", "u3", "timer_paused", "Paused timer (auto — moved to On Hold)", hoursAgo(5)),
  auditEntry("a30", "t11", "u3", "status_changed", "In Progress → On Hold", hoursAgo(5)),
  auditEntry("a31", "t12", "u1", "created", "Created task", daysAgo(2)),
  auditEntry("a32", "t12", "u1", "status_changed", "To Do → In Progress", hoursAgo(6)),
  auditEntry("a33", "t12", "u1", "timer_started", "Started timer", hoursAgo(6)),
  auditEntry("a34", "t12", "u1", "timer_paused", "Paused timer (auto — moved to On Hold)", hoursAgo(2)),
  auditEntry("a35", "t12", "u1", "status_changed", "In Progress → On Hold", hoursAgo(2)),

  // Completed tasks — full Start -> Stop lifecycle.
  auditEntry("a36", "t13", "u1", "created", "Created task", daysAgo(3)),
  auditEntry("a37", "t13", "u1", "status_changed", "To Do → In Progress", daysAgo(2)),
  auditEntry("a38", "t13", "u1", "timer_started", "Started timer", daysAgo(2)),
  auditEntry("a39", "t13", "u1", "status_changed", "In Progress → Completed", daysAgo(2)),
  auditEntry("a40", "t13", "u1", "timer_stopped", "Stopped timer — task completed", daysAgo(2)),
  auditEntry("a41", "t14", "u4", "created", "Created task", daysAgo(10)),
  auditEntry("a42", "t14", "u4", "status_changed", "To Do → In Progress", daysAgo(7)),
  auditEntry("a43", "t14", "u4", "timer_started", "Started timer", daysAgo(7)),
  auditEntry("a44", "t14", "u4", "status_changed", "In Progress → Completed", daysAgo(7)),
  auditEntry("a45", "t14", "u4", "timer_stopped", "Stopped timer — task completed", daysAgo(7)),
  auditEntry("a46", "t15", "u2", "created", "Created task", daysAgo(4)),
  auditEntry("a47", "t15", "u2", "status_changed", "To Do → In Progress", daysAgo(4)),
  auditEntry("a48", "t15", "u2", "timer_started", "Started timer", daysAgo(4)),
  auditEntry("a49", "t15", "u2", "status_changed", "In Progress → Completed", daysAgo(4)),
  auditEntry("a50", "t15", "u2", "timer_stopped", "Stopped timer — task completed", daysAgo(4)),
];

export const DEFAULT_BOARD_CONFIG: BoardConfig = {
  swimlane_field: "assignee",
  updated_at: daysAgo(30),
};
