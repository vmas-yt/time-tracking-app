import type {
  AuditEntry,
  BoardConfig,
  Comment,
  CumulativeFlowPoint,
  CustomField,
  CustomFieldType,
  CycleTimePoint,
  Department,
  DropdownOption,
  DropdownOptionScope,
  LeadTimePoint,
  ManualEntrySettings,
  Project,
  ReminderCandidate,
  Role,
  RolePermissionAuditEntry,
  SwimlaneField,
  Task,
  TaskCategory,
  TaskPriority,
  TaskStatus,
  TaskType,
  Team,
  TeamBoardConfig,
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
    // Round B3 (docs/design/custom-roles-design.md §4.2): `role` and
    // `role_id` are mutually exclusive — send at most one. `role` picks a
    // builtin by enum value (existing behavior, unchanged); `role_id` picks
    // any row (builtin or custom) by id, the only way to assign a custom
    // role. The backend 400s if both are present and non-null; the frontend
    // doesn't pre-validate that here since enforcement is the backend's job.
    role?: UserRole;
    role_id?: string | null;
    manager_id?: string | null;
    team_id?: string | null;
    password: string;
  }) => request<User>("/users", { method: "POST", body: JSON.stringify(input) }),
  updateUser: (
    userId: string,
    input: Partial<{
      full_name: string;
      email: string;
      // Same mutual-exclusivity note as `createUser` above (§4.2).
      role: UserRole;
      role_id: string | null;
      manager_id: string | null;
      team_id: string | null;
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
  updateProject: (projectId: string, input: Partial<{ name: string; description: string }>) =>
    request<Project>(`/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(input) }),
  deleteProject: (projectId: string) => request<void>(`/projects/${projectId}`, { method: "DELETE" }),

  // Round A org structure — Departments/Teams. `include_inactive` mirrors
  // `listUsers`'s own param so a deactivated department/team keeps showing
  // (grayed out, with a Reactivate action) instead of vanishing from the
  // admin table it was managed from.
  listDepartments: (params?: { includeInactive?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.includeInactive) query.set("include_inactive", "true");
    const qs = query.toString();
    return request<Department[]>(`/departments${qs ? `?${qs}` : ""}`);
  },
  createDepartment: (name: string) =>
    request<Department>("/departments", { method: "POST", body: JSON.stringify({ name }) }),
  updateDepartment: (departmentId: string, input: Partial<{ name: string; is_active: boolean }>) =>
    request<Department>(`/departments/${departmentId}`, { method: "PATCH", body: JSON.stringify(input) }),
  // Despite the verb, soft-deactivates (sets is_active=false) and returns
  // the updated Department — same shape as `deactivateUser`. 409 if the
  // department still has active teams under it, surfaced verbatim by
  // callers via `errorMessage`, same as `deleteProject`'s "has tasks linked
  // to it" guard.
  deactivateDepartment: (departmentId: string) =>
    request<Department>(`/departments/${departmentId}`, { method: "DELETE" }),

  listTeams: (params?: { departmentId?: string; includeInactive?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.departmentId) query.set("department_id", params.departmentId);
    if (params?.includeInactive) query.set("include_inactive", "true");
    const qs = query.toString();
    return request<Team[]>(`/teams${qs ? `?${qs}` : ""}`);
  },
  createTeam: (input: { name: string; department_id: string; manager_id?: string | null }) =>
    request<Team>("/teams", { method: "POST", body: JSON.stringify(input) }),
  updateTeam: (
    teamId: string,
    input: Partial<{ name: string; department_id: string; manager_id: string | null; is_active: boolean }>
  ) => request<Team>(`/teams/${teamId}`, { method: "PATCH", body: JSON.stringify(input) }),
  // Despite the verb, soft-deactivates and returns the updated Team — same
  // shape as `deactivateDepartment` above. 409 if the team still has active
  // members assigned to it.
  deactivateTeam: (teamId: string) => request<Team>(`/teams/${teamId}`, { method: "DELETE" }),

  // Round B3 custom roles (docs/design/custom-roles-design.md §2). Unlike
  // Departments/Teams, `GET /roles` is open-read for any authenticated user
  // (the Users screen's role picker needs it), and `DELETE` is a real hard
  // delete (§2.5) rather than a soft-deactivate — matching
  // `deleteCustomField`'s `void`/204 convention below, not
  // `deactivateDepartment`/`deactivateTeam`'s "returns the updated row" one.
  // Named `getRoles` (not `listRoles`, despite `listUsers`/`listDepartments`/
  // `listTeams`'s naming convention elsewhere in this file) to match the
  // exact call site name pinned for this round.
  getRoles: () => request<Role[]>("/roles"),
  createRole: (name: string) => request<Role>("/roles", { method: "POST", body: JSON.stringify({ name }) }),
  updateRole: (roleId: string, name: string) =>
    request<Role>(`/roles/${roleId}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  // Full-set replacement, not incremental add/remove (§2.4) — always send
  // the complete list of keys the role should hold after this call.
  updateRolePermissions: (roleId: string, permissionKeys: string[]) =>
    request<Role>(`/roles/${roleId}/permissions`, {
      method: "PUT",
      body: JSON.stringify({ permission_keys: permissionKeys }),
    }),
  // 409s if built-in, still occupied by a user (active or inactive, §6.3),
  // or has any permission-change history (§2.5) — surfaced verbatim by
  // callers via `errorMessage`, same as `deleteProject`'s guard.
  deleteRole: (roleId: string) => request<void>(`/roles/${roleId}`, { method: "DELETE" }),
  getRoleAudit: (roleId: string) => request<RolePermissionAuditEntry[]>(`/roles/${roleId}/audit`),

  listTasks: (params?: {
    projectId?: string;
    assigneeId?: string;
    status?: TaskStatus;
    managerId?: string;
    // Round C (docs/design/team-scoped-boards-design.md §4.4) — plain
    // additional filter, same shape/precedent as `managerId`/`projectId`
    // above (`GET /tasks?team_id=`).
    teamId?: string;
    includeArchived?: boolean;
  }) => {
    const query = new URLSearchParams();
    if (params?.projectId) query.set("project_id", params.projectId);
    if (params?.assigneeId) query.set("assignee_id", params.assigneeId);
    if (params?.status) query.set("status_filter", params.status);
    if (params?.managerId) query.set("manager_id", params.managerId);
    if (params?.teamId) query.set("team_id", params.teamId);
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
  // Manual/retroactive time-logging: creates a task and its first logged
  // time entry in one call, backdated to `start_date`/`completion_date`
  // (bounded server-side by the admin's `max_days_back` policy — see
  // `getManualEntrySettings` below). Same task fields as `createTask` plus
  // the manual-log trio.
  createManualTask: (input: {
    title: string;
    project_id?: string | null;
    description?: string;
    task_type?: TaskType;
    category: TaskCategory;
    category_other_text?: string;
    priority?: TaskPriority;
    assignee_id?: string | null;
    team_id?: string | null;
    custom_values?: Record<string, string>;
    start_date: string;
    completion_date: string;
    duration_minutes: number;
  }) => request<Task>("/tasks/manual-log", { method: "POST", body: JSON.stringify(input) }),
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
  // Adds a backdated time entry to an existing task (as opposed to
  // `createManualTask`, which creates the task too) — same `max_days_back`
  // bound applies server-side.
  logManualTimeForTask: (
    taskId: string,
    payload: { start_date: string; completion_date: string; duration_minutes: number }
  ) => request<Task>(`/tasks/${taskId}/manual-log`, { method: "POST", body: JSON.stringify(payload) }),

  getBoardConfig: () => request<BoardConfig>("/admin/board-config"),
  updateBoardConfig: (swimlane_field: SwimlaneField) =>
    request<BoardConfig>("/admin/board-config", {
      method: "PATCH",
      body: JSON.stringify({ swimlane_field }),
    }),
  // Round C (docs/design/team-scoped-boards-design.md §4.1/§4.2) — the
  // per-team analogue of `getBoardConfig`/`updateBoardConfig` above. Open-read
  // for any authenticated user (mirrors the global endpoint's own open-read);
  // `PATCH` is a partial update (both fields optional) — an explicit
  // `board_name: null` clears back to the `Team.name` fallback, an omitted
  // key leaves it unchanged.
  getTeamBoardConfig: (teamId: string) => request<TeamBoardConfig>(`/teams/${teamId}/board-config`),
  updateTeamBoardConfig: (teamId: string, input: { board_name?: string | null; swimlane_field?: SwimlaneField }) =>
    request<TeamBoardConfig>(`/teams/${teamId}/board-config`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  // Manual/retroactive time-logging policy — how many days back a manual
  // entry's start/completion date may be backdated. Readable by any
  // authenticated user (the manual-log form needs it to bound its date
  // pickers); only admins can PATCH it. `0` is a valid value ("only today").
  getManualEntrySettings: () => request<ManualEntrySettings>("/admin/manual-entry-settings"),
  updateManualEntrySettings: (maxDaysBack: number) =>
    request<ManualEntrySettings>("/admin/manual-entry-settings", {
      method: "PATCH",
      body: JSON.stringify({ max_days_back: maxDaysBack }),
    }),
  listCustomFields: () => request<CustomField[]>("/admin/custom-fields"),
  createCustomField: (input: { name: string; field_type: CustomFieldType; options?: string[] }) =>
    request<CustomField>("/admin/custom-fields", { method: "POST", body: JSON.stringify(input) }),
  updateCustomField: (fieldId: string, input: { name: string }) =>
    request<CustomField>(`/admin/custom-fields/${fieldId}`, { method: "PATCH", body: JSON.stringify(input) }),
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
