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
  role: UserRole;
  manager_id: string | null;
  team_id: string | null;
  is_active: boolean;
  deactivated_at: string | null;
  created_at: string;
}

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
