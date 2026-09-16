import type { Project, Task, TaskStatus, TimeEntry, User } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
    throw new Error(detail.detail ?? "Request failed");
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

  listProjects: () => request<Project[]>("/projects"),
  createProject: (name: string, description?: string) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify({ name, description }) }),

  listTasks: (projectId?: string) =>
    request<Task[]>(`/tasks${projectId ? `?project_id=${projectId}` : ""}`),
  createTask: (input: { title: string; project_id: string; description?: string }) =>
    request<Task>("/tasks", { method: "POST", body: JSON.stringify(input) }),
  updateTaskStatus: (taskId: string, status: TaskStatus, position: number) =>
    request<Task>(`/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status, position }),
    }),

  getActiveTimer: () => request<TimeEntry | null>("/time-entries/active"),
  startTimer: (taskId: string) =>
    request<TimeEntry>(`/time-entries/start?task_id=${taskId}`, { method: "POST" }),
  pauseTimer: (entryId: string) =>
    request<TimeEntry>(`/time-entries/${entryId}/pause`, { method: "POST" }),
  resumeTimer: (entryId: string) =>
    request<TimeEntry>(`/time-entries/${entryId}/resume`, { method: "POST" }),
  stopTimer: (entryId: string) =>
    request<TimeEntry>(`/time-entries/${entryId}/stop`, { method: "POST" }),
};
