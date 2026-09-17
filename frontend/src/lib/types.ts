export type UserRole = "employee" | "manager" | "admin";

export type TaskType = "normal" | "ad_hoc";

export type TaskCategory =
  | "production_issue"
  | "urgent_request"
  | "meeting"
  | "support_ticket"
  | "cyber_security_request"
  | "platform_support"
  | "infrastructure"
  | "other";

export type TaskPriority = "normal" | "expedite";

export type TaskStatus = "backlog" | "todo" | "in_progress" | "on_hold" | "completed";

export type TimerStatus = "running" | "paused" | "stopped";

export type SwimlaneField = "assignee" | "task_type" | "category" | "priority";

export type CustomFieldType = "text" | "number" | "select" | "date" | "boolean";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  manager_id: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
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
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  custom_values: Record<string, string>;
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

export interface CustomField {
  id: string;
  name: string;
  field_type: CustomFieldType;
  options: string[] | null;
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

export const SWIMLANE_FIELDS: { key: SwimlaneField; label: string }[] = [
  { key: "assignee", label: "Team member" },
  { key: "task_type", label: "Task type" },
  { key: "category", label: "Category" },
  { key: "priority", label: "Priority" },
];
