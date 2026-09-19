export type UserRole = "employee" | "manager" | "admin";

export type TaskType = "normal" | "ad_hoc";

// Category/priority moved from fixed backend enums to admin-editable,
// DB-validated free strings (docs/design/custom-fields-admin-design.md §2) —
// the valid set now lives in `DropdownOption` rows (see `DropdownOption`
// below), not in the TypeScript type system. `TASK_CATEGORIES`/
// `TASK_PRIORITIES` below remain only as the seeded-default label set to
// fall back on before the live dropdown-options fetch resolves.
export type TaskCategory = string;

export type TaskPriority = string;

export type TaskStatus = "backlog" | "todo" | "in_progress" | "on_hold" | "completed";

export type TimerStatus = "running" | "paused" | "stopped";

export type SwimlaneField = "assignee" | "task_type" | "category" | "priority";

export type CustomFieldType = "text" | "number" | "select" | "date" | "boolean";

export type DropdownOptionScope = "task_category" | "task_priority" | "custom_field";

export interface User {
  id: string;
  email: string;
  full_name: string;
  // Round B3 (docs/design/custom-roles-design.md §4.1/§4.4): nullable, not a
  // pre-existing-but-untriggered bug fix — the legacy three-way enum has no
  // valid value to hold for a user assigned a genuinely custom role, and
  // becomes `null` on the wire for that user. Every existing caller keying
  // off this field for a builtin employee/manager/admin user is unaffected;
  // callers must handle `null` (a custom-role holder) explicitly rather than
  // indexing a `Record<UserRole, ...>` with it directly. Prefer `role_name`
  // below for display — it's already resolved server-side for both builtin
  // and custom roles.
  role: UserRole | null;
  // Round B3: FK to the `Role` row backing this user (builtin or custom) —
  // always non-null in practice (every user has a resolved role row), typed
  // nullable to match the wire contract exactly (§4.1).
  role_id: string | null;
  // Round B3: server-resolved display name for `role_id`'s row — works
  // uniformly whether the user holds a builtin or custom role. This is the
  // field to render in place of a `ROLE_LABEL[user.role]` lookup.
  role_name: string;
  manager_id: string | null;
  team_id: string | null;
  is_active: boolean;
  deactivated_at: string | null;
  created_at: string;
}

// Round B3 (docs/design/custom-roles-design.md §2). A `Role` row — builtin
// (employee/manager/admin, fixed, not permission-configurable — §2.4) or
// custom (admin-created via `POST /roles`, permission set fully replaceable
// via `PUT /roles/{id}/permissions`). `permission_keys` is `string[]`, not
// `PermissionKey[]`: it's server-echoed data that should round-trip safely
// even if the frontend's catalog copy (`PERMISSION_CATALOG` below) ever lags
// behind a backend-added key, same defensive-typing rationale as
// `TaskCategory`/`TaskPriority` above.
export interface Role {
  id: string;
  key: string;
  name: string;
  is_builtin: boolean;
  permission_keys: string[];
  created_at: string;
}

// Round B3 §2.7 — `GET /roles/{id}/audit`'s response shape, already grouped
// by `batch_id` server-side (one entry per `PUT /roles/{id}/permissions`
// call, not one row per changed permission key — see the design doc's own
// `RolePermissionAuditEntry` DB model docstring for why the *storage* shape
// is one-row-per-key while this, the *read* shape, folds those rows back
// into `added`/`removed` lists per batch). `actor` is the acting admin's
// identity, not a bare id, matching the exact JSON in §2.7 (a resolved
// `{ id, full_name, email }`, the same shape already used elsewhere for
// resolved-actor display, e.g. `ReminderCandidate`) — deliberately *not*
// the flatter `actor_id: string` sometimes assumed, since the endpoint
// resolves and returns the full identity so the History panel (§5.1) never
// needs a second lookup against the (possibly since-deactivated) actor.
export interface RolePermissionAuditEntry {
  batch_id: string;
  actor: { id: string; full_name: string; email: string };
  occurred_at: string;
  added: string[];
  removed: string[];
}

// Round B3 §1.3 — the full grantable permission catalog (12 keys). Deliberately
// excludes `manage_roles_permissions`: there is no such permission (§1.1),
// managing roles/permissions stays floor-admin-only (`assert_admin`),
// never delegable via this catalog.
export type PermissionKey =
  | "manage_departments"
  | "manage_teams"
  | "manage_projects"
  | "manage_custom_fields"
  | "manage_dropdown_options"
  | "manage_board_config"
  | "manage_manual_entry_settings"
  | "archive_tasks"
  | "view_all_tasks"
  | "view_all_time_entries"
  | "view_reports_all"
  | "view_all_reminders";

// The three §5.1 checklist groupings for the future `RolePermissionsPanel`.
export type PermissionGroup = "Organization" | "Board & task admin" | "Visibility";

// key -> { label, group } — mirrors the `Record`-of-metadata shape this file
// otherwise expresses as `{ key, label }[]` arrays (`TASK_CATEGORIES` etc.),
// but keyed by permission for O(1) lookup from a checkbox list, since the
// consumer (§5.1's `RolePermissionsPanel`) needs to look up a label for an
// arbitrary already-known key far more often than it needs to iterate in a
// fixed display order. `PERMISSION_KEYS` below covers the iteration case.
export const PERMISSION_CATALOG: Record<PermissionKey, { label: string; group: PermissionGroup }> = {
  manage_departments: { label: "Manage departments", group: "Organization" },
  manage_teams: { label: "Manage teams", group: "Organization" },
  manage_projects: { label: "Manage projects", group: "Organization" },
  manage_custom_fields: { label: "Manage custom fields", group: "Board & task admin" },
  manage_dropdown_options: { label: "Manage dropdown options", group: "Board & task admin" },
  manage_board_config: { label: "Change swim-lane grouping", group: "Board & task admin" },
  manage_manual_entry_settings: { label: "Change manual time-entry policy", group: "Board & task admin" },
  archive_tasks: { label: "Archive/unarchive tasks", group: "Board & task admin" },
  view_all_tasks: { label: "View all tasks", group: "Visibility" },
  view_all_time_entries: { label: "View & control all time entries", group: "Visibility" },
  view_reports_all: { label: "View all reports", group: "Visibility" },
  view_all_reminders: { label: "View all reminders", group: "Visibility" },
};

// Stable iteration order (catalog table order, §1.3) for rendering the
// checklist grouped by `PermissionGroup` — `Object.keys` order on a
// string-keyed object is insertion order in practice, but an explicit const
// array avoids relying on that for display ordering.
export const PERMISSION_KEYS: PermissionKey[] = [
  "manage_departments",
  "manage_teams",
  "manage_projects",
  "manage_custom_fields",
  "manage_dropdown_options",
  "manage_board_config",
  "manage_manual_entry_settings",
  "archive_tasks",
  "view_all_tasks",
  "view_all_time_entries",
  "view_reports_all",
  "view_all_reminders",
];

export interface Project {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
}

// Round A org structure (docs/PRD.md-adjacent design work): Department is the
// top-level grouping, Team sits under a Department and carries the
// "derived, auto-synced" manager relationship — a User assigned to a Team
// has their `manager_id` silently kept in sync with the Team's manager by
// the backend (see `UserFormPanel`'s read-only Manager field once
// `team_id` is set).
export interface Department {
  id: string;
  name: string;
  is_active: boolean;
  created_at: string;
}

export interface Team {
  id: string;
  name: string;
  department_id: string;
  manager_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: string;
  project_id: string | null;
  assignee_id: string | null;
  created_by_id: string;
  title: string;
  description: string | null;
  task_type: TaskType;
  category: TaskCategory;
  category_other_text: string | null;
  priority: TaskPriority;
  status: TaskStatus;
  position: number;
  team_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  archived_at: string | null;
  custom_values: Record<string, string>;
  total_logged_seconds: number;
  // Manual/retroactive time-logging (docs/PRD.md-adjacent design work):
  // `started_at` is when the task's timer/manual entry actually began (as
  // opposed to `created_at`, which is when the task row was created);
  // `is_manual_entry` flags a task created or logged via the manual-entry
  // flow rather than the live Start/Pause/Stop timer; `card_date` is the
  // backend-computed date the board should display on the card (manual
  // entries show their logged date rather than `created_at`).
  started_at: string | null;
  is_manual_entry: boolean;
  card_date: string;
}

export interface TimeEntry {
  id: string;
  task_id: string;
  user_id: string;
  status: TimerStatus;
  started_at: string;
  last_resumed_at: string | null;
  accumulated_seconds: number;
  ended_at: string | null;
  elapsed_seconds: number;
  // True when this entry was created via the manual-log endpoints rather
  // than the live Start/Pause/Stop timer flow.
  is_manual: boolean;
}

// Admin-configurable policy for the manual/retroactive time-logging
// feature: how many days back a manual entry's start/completion date may
// be backdated. `0` is a valid, meaningful value ("only today, no
// backdating") — not an unset/error state.
export interface ManualEntrySettings {
  max_days_back: number;
  updated_at: string;
}

/** Body shared by both manual-log endpoints (`POST /tasks/manual-log`'s
 * trailing fields, and the whole body of `POST /tasks/{id}/manual-log`).
 * Dates are plain `YYYY-MM-DD` strings — an HTML date input's native value —
 * not full timestamps; there's no time-of-day component to a manually
 * logged day. */
export interface ManualLogInput {
  start_date: string;
  completion_date: string;
  duration_minutes: number;
}

export interface Comment {
  id: string;
  task_id: string;
  author_id: string;
  body: string;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  task_id: string;
  actor_id: string;
  action: string;
  detail: string;
  created_at: string;
}

export interface DropdownOption {
  id: string;
  scope: DropdownOptionScope;
  custom_field_id: string | null;
  value: string;
  label: string;
  is_builtin: boolean;
  is_active: boolean;
  position: number;
  created_at: string;
}

// Identical shape to DropdownOption on the wire (see schemas.py's
// `CustomFieldOptionRead = DropdownOptionRead` alias) — named separately per
// the design doc's frontend contract (§1.4).
export type CustomFieldOption = DropdownOption;

export interface CustomField {
  id: string;
  name: string;
  field_type: CustomFieldType;
  options: CustomFieldOption[] | null;
  created_at: string;
}

export interface BoardConfig {
  swimlane_field: SwimlaneField;
  updated_at: string;
  // Round C (docs/design/team-scoped-boards-design.md §4.3/§5.3): server-
  // computed `has_permission(current_user, Permission.MANAGE_BOARD_CONFIG)` —
  // the same boolean the `PATCH` handler itself checks before its own `403`.
  // This is the fix for the pre-existing `board/store.tsx` bug that derived
  // "can manage the board config" from the legacy `role === "admin"` string
  // instead of the real, server-side permission: a custom role granted
  // `manage_board_config` (Round B3) couldn't actually use the "Group lanes
  // by" control even though the backend would accept the `PATCH`. Read this
  // field directly rather than re-deriving permission from `currentUser.role`.
  can_manage: boolean;
}

// Round C (docs/design/team-scoped-boards-design.md §4.1/§4.2) — the
// per-team analogue of `BoardConfig` above. One row per `Team` (lazily
// created on first read/write, same idiom as the global singleton),
// holding the two things configurable about that team's board: which field
// groups cards into swim lanes, and an optional display name independent
// of `Team.name` (falls back to the team's own name when null, §3 of the
// design doc). `can_manage` is server-computed exactly like `BoardConfig`'s
// own field above — same fix, applied identically to both endpoints so the
// global and per-team screens never diverge on how they derive permission.
export interface TeamBoardConfig {
  team_id: string;
  board_name: string | null;
  swimlane_field: SwimlaneField;
  updated_at: string;
  can_manage: boolean;
}

export interface CycleTimePoint {
  task_id: string;
  title: string;
  started_at: string;
  completed_at: string;
  cycle_time_seconds: number;
}

export interface LeadTimePoint {
  task_id: string;
  title: string;
  created_at: string;
  completed_at: string;
  lead_time_seconds: number;
}

export interface ThroughputBucket {
  period_start: string;
  completed_count: number;
}

export interface CumulativeFlowPoint {
  date: string;
  counts: Record<string, number>;
}

export interface ReminderCandidate {
  user_id: string;
  full_name: string;
  email: string;
  manager_id: string | null;
  last_logged_at: string | null;
}

export const TASK_STATUSES: { key: TaskStatus; label: string }[] = [
  { key: "backlog", label: "Backlog" },
  { key: "todo", label: "To Do" },
  { key: "in_progress", label: "In Progress" },
  { key: "on_hold", label: "On Hold" },
  { key: "completed", label: "Completed" },
];

// Seed-default label sets — mirrors the backend's `ensure_default_dropdown_
// options()` seed exactly (docs/design/custom-fields-admin-design.md §2.4).
// Used only as a fallback before `GET /admin/dropdown-options` resolves, or
// as a last-resort label lookup for a stored value no longer present in the
// live (active-only) options list. The live list is always the source of
// truth for what's selectable — these never gate a request client-side.
export const TASK_CATEGORIES: { key: TaskCategory; label: string }[] = [
  { key: "production_issue", label: "Production Issue" },
  { key: "urgent_request", label: "Urgent Request" },
  { key: "meeting", label: "Meeting" },
  { key: "support_ticket", label: "Support Ticket" },
  { key: "cyber_security_request", label: "Cyber Security Request" },
  { key: "platform_support", label: "Platform Support" },
  { key: "infrastructure", label: "Infrastructure" },
  { key: "other", label: "Others" },
];

export const TASK_PRIORITIES: { key: TaskPriority; label: string }[] = [
  { key: "normal", label: "Normal" },
  { key: "expedite", label: "Expedite" },
];

export const SWIMLANE_FIELDS: { key: SwimlaneField; label: string }[] = [
  { key: "assignee", label: "Team member" },
  { key: "task_type", label: "Task type" },
  { key: "category", label: "Category" },
  { key: "priority", label: "Priority" },
];
