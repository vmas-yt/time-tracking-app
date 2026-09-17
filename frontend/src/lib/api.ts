import type {
  AuditEntry,
  BoardConfig,
  Comment,
  CumulativeFlowPoint,
  CustomField,
  CustomFieldType,
  CycleTimePoint,
  DropdownOption,
  DropdownOptionScope,
  LeadTimePoint,
  Project,
  ReminderCandidate,
  SwimlaneField,
  Task,
  TaskCategory,
  TaskPriority,
  TaskStatus,
  TaskType,
  ThroughputBucket,
  TimeEntry,
  User,
  UserRole,
} from "./types";

// Render's `fromService`/`property: host` binding (used in render.yaml so the
// deployed frontend always points at wherever the backend actually landed,
// rather than a hardcoded hostname that breaks the moment Render assigns a
// random suffix) yields a bare host with no scheme — add one if it's missing.
const rawApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_URL = /^https?:\/\//.test(rawApiUrl) ? rawApiUrl : `https://${rawApiUrl}`;

// Thrown for any non-2xx response. Carries the HTTP status so callers can
// distinguish "not authorized" (403) / "conflict" (409) from other failures
// if they ever need to branch on it — today every caller just surfaces
// `.message` in a toast, but the status is there rather than discarded.
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function authHeaders(): HeadersInit {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...options.headers,
    },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(detail.detail ?? "Request failed", res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  login: (email: string, password: string) => {
    const body = new URLSearchParams({ username: email, password });
    return fetch(`${API_URL}/auth/login`, { method: "POST", body }).then(async (res) => {
      if (!res.ok) throw new Error("Invalid credentials");
      return res.json() as Promise<{ access_token: string }>;
    });
  },
  me: () => request<User>("/users/me"),
  listUsers: (params?: { includeInactive?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.includeInactive) query.set("include_inactive", "true");
    const qs = query.toString();
    return request<User[]>(`/users${qs ? `?${qs}` : ""}`);
  },
  createUser: (input: {
    email: string;
    full_name: string;
    role?: UserRole;
    manager_id?: string | null;
    password: string;
  }) => request<User>("/users", { method: "POST", body: JSON.stringify(input) }),
  updateUser: (
    userId: string,
    input: Partial<{
      full_name: string;
      email: string;
      role: UserRole;
      manager_id: string | null;
      is_active: boolean;
    }>
  ) => request<User>(`/users/${userId}`, { method: "PATCH", body: JSON.stringify(input) }),
  resetPassword: (userId: string, newPassword: string) =>
    request<void>(`/users/${userId}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    }),
  deactivateUser: (userId: string) => request<User>(`/users/${userId}`, { method: "DELETE" }),

  listProjects: () => request<Project[]>("/projects"),
  getProject: (projectId: string) => request<Project>(`/projects/${projectId}`),
  createProject: (name: string, description?: string) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify({ name, description }) }),
  deleteProject: (projectId: string) => request<void>(`/projects/${projectId}`, { method: "DELETE" }),

  listTasks: (params?: {
    projectId?: string;
    assigneeId?: string;
    status?: TaskStatus;
    managerId?: string;
    includeArchived?: boolean;
  }) => {
    const query = new URLSearchParams();
    if (params?.projectId) query.set("project_id", params.projectId);
    if (params?.assigneeId) query.set("assignee_id", params.assigneeId);
    if (params?.status) query.set("status_filter", params.status);
    if (params?.managerId) query.set("manager_id", params.managerId);
    if (params?.includeArchived) query.set("include_archived", "true");
    const qs = query.toString();
    return request<Task[]>(`/tasks${qs ? `?${qs}` : ""}`);
  },
  createTask: (input: {
    title: string;
    project_id?: string | null;
    description?: string;
    task_type?: TaskType;
    category: TaskCategory;
    category_other_text?: string;
    priority?: TaskPriority;
    assignee_id?: string | null;
    custom_values?: Record<string, string>;
  }) => request<Task>("/tasks", { method: "POST", body: JSON.stringify(input) }),
  getTask: (taskId: string) => request<Task>(`/tasks/${taskId}`),
  updateTask: (
    taskId: string,
    input: Partial<{
      title: string;
      description: string;
      project_id: string | null;
      assignee_id: string | null;
      category: TaskCategory;
      category_other_text: string;
      priority: TaskPriority;
      position: number;
      status: TaskStatus;
      custom_values: Record<string, string>;
    }>
  ) => request<Task>(`/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify(input) }),
  deleteTask: (taskId: string) => request<void>(`/tasks/${taskId}`, { method: "DELETE" }),
  archiveTask: (taskId: string) => request<Task>(`/tasks/${taskId}/archive`, { method: "POST" }),
  unarchiveTask: (taskId: string) => request<Task>(`/tasks/${taskId}/unarchive`, { method: "POST" }),

  listComments: (taskId: string) => request<Comment[]>(`/tasks/${taskId}/comments`),
  addComment: (taskId: string, body: string) =>
    request<Comment>(`/tasks/${taskId}/comments`, { method: "POST", body: JSON.stringify({ body }) }),
  listAudit: (taskId: string) => request<AuditEntry[]>(`/tasks/${taskId}/audit`),

  listTimeEntries: (params?: { taskId?: string }) => {
    const query = new URLSearchParams();
    if (params?.taskId) query.set("task_id", params.taskId);
    const qs = query.toString();
    return request<TimeEntry[]>(`/time-entries${qs ? `?${qs}` : ""}`);
  },
  listOpenTimers: () => request<TimeEntry[]>("/time-entries/open"),
  startTimer: (taskId: string) =>
    request<TimeEntry>(`/time-entries/start?task_id=${taskId}`, { method: "POST" }),
  pauseTimer: (entryId: string) =>
    request<TimeEntry>(`/time-entries/${entryId}/pause`, { method: "POST" }),
  resumeTimer: (entryId: string) =>
    request<TimeEntry>(`/time-entries/${entryId}/resume`, { method: "POST" }),
  stopTimer: (entryId: string) =>
    request<TimeEntry>(`/time-entries/${entryId}/stop`, { method: "POST" }),

  getBoardConfig: () => request<BoardConfig>("/admin/board-config"),
  updateBoardConfig: (swimlane_field: SwimlaneField) =>
    request<BoardConfig>("/admin/board-config", {
      method: "PATCH",
      body: JSON.stringify({ swimlane_field }),
    }),
  listCustomFields: () => request<CustomField[]>("/admin/custom-fields"),
  createCustomField: (input: { name: string; field_type: CustomFieldType; options?: string[] }) =>
    request<CustomField>("/admin/custom-fields", { method: "POST", body: JSON.stringify(input) }),
  deleteCustomField: (fieldId: string) =>
    request<void>(`/admin/custom-fields/${fieldId}`, { method: "DELETE" }),

  listDropdownOptions: (params: {
    scope: DropdownOptionScope;
    customFieldId?: string;
    includeInactive?: boolean;
  }) => {
    const query = new URLSearchParams({ scope: params.scope });
    if (params.customFieldId) query.set("custom_field_id", params.customFieldId);
    if (params.includeInactive) query.set("include_inactive", "true");
    return request<DropdownOption[]>(`/admin/dropdown-options?${query.toString()}`);
  },
  createDropdownOption: (input: {
    scope: DropdownOptionScope;
    custom_field_id?: string | null;
    value: string;
    label?: string;
  }) => request<DropdownOption>("/admin/dropdown-options", { method: "POST", body: JSON.stringify(input) }),
  updateDropdownOption: (
    optionId: string,
    input: Partial<{ label: string; is_active: boolean; position: number }>
  ) =>
    request<DropdownOption>(`/admin/dropdown-options/${optionId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  deactivateDropdownOption: (optionId: string) =>
    request<DropdownOption>(`/admin/dropdown-options/${optionId}`, { method: "DELETE" }),

  reportCycleTime: () => request<CycleTimePoint[]>("/reports/cycle-time"),
  reportControlChart: () => request<CycleTimePoint[]>("/reports/control-chart"),
  reportLeadTime: () => request<LeadTimePoint[]>("/reports/lead-time"),
  reportThroughput: (interval: "day" | "week" = "day") =>
    request<ThroughputBucket[]>(`/reports/throughput?interval=${interval}`),
  reportCumulativeFlow: (days = 30) =>
    request<CumulativeFlowPoint[]>(`/reports/cumulative-flow?days=${days}`),

  reminderCandidates: (days = 1) => request<ReminderCandidate[]>(`/notifications/reminders?days=${days}`),
};
