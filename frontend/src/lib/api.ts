import type {
  AuditEntry,
  BoardConfig,
  Comment,
  CumulativeFlowPoint,
  CustomField,
  CustomFieldType,
  CycleTimePoint,
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

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  register: (email: string, full_name: string, password: string) =>
    request<User>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, full_name, password }),
    }),
  me: () => request<User>("/users/me"),
  listUsers: () => request<User[]>("/users"),
  updateUser: (userId: string, input: { role?: UserRole; manager_id?: string | null }) =>
    request<User>(`/users/${userId}`, { method: "PATCH", body: JSON.stringify(input) }),

  listProjects: () => request<Project[]>("/projects"),
  getProject: (projectId: string) => request<Project>(`/projects/${projectId}`),
  createProject: (name: string, description?: string) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify({ name, description }) }),

  listTasks: (params?: {
    projectId?: string;
    assigneeId?: string;
    status?: TaskStatus;
    managerId?: string;
  }) => {
    const query = new URLSearchParams();
    if (params?.projectId) query.set("project_id", params.projectId);
    if (params?.assigneeId) query.set("assignee_id", params.assigneeId);
    if (params?.status) query.set("status_filter", params.status);
    if (params?.managerId) query.set("manager_id", params.managerId);
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
  }) => request<Task>("/tasks", { method: "POST", body: JSON.stringify(input) }),
  getTask: (taskId: string) => request<Task>(`/tasks/${taskId}`),
  updateTask: (
    taskId: string,
    input: Partial<{
      title: string;
      description: string;
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

  reportCycleTime: () => request<CycleTimePoint[]>("/reports/cycle-time"),
  reportControlChart: () => request<CycleTimePoint[]>("/reports/control-chart"),
  reportLeadTime: () => request<LeadTimePoint[]>("/reports/lead-time"),
  reportThroughput: (interval: "day" | "week" = "day") =>
    request<ThroughputBucket[]>(`/reports/throughput?interval=${interval}`),
  reportCumulativeFlow: (days = 30) =>
    request<CumulativeFlowPoint[]>(`/reports/cumulative-flow?days=${days}`),

  reminderCandidates: (days = 1) => request<ReminderCandidate[]>(`/notifications/reminders?days=${days}`),
};
