import type { AuditEntry, Comment, Task, TaskStatus, TimeEntry } from "@/lib/types";
import { CURRENT_USER_ID } from "./seed";

// ---------------------------------------------------------------------------
// Pure state-machine implementation of docs/design/kanban-timer-design.md §3.
// No React, no I/O — every function takes the current slice of state and
// returns either a rejection reason (guard failed) or the next state plus
// the audit entries the transition produced. This is the client-side dummy
// stand-in for the backend transition rules in the design doc, kept in one
// place so the UI layer never has to re-derive "is this allowed?" itself.
// ---------------------------------------------------------------------------

export interface EngineState {
  tasks: Task[];
  entries: TimeEntry[];
  audit: AuditEntry[];
  comments: Comment[];
}

export type EngineResult =
  | { ok: true; state: EngineState }
  | { ok: false; reason: string };

let idCounter = 100;
function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}${idCounter}`;
}

const STATUS_LABEL: Record<TaskStatus, string> = {
  backlog: "Backlog",
  todo: "To Do",
  in_progress: "In Progress",
  on_hold: "On Hold",
  completed: "Completed",
};

function statusChangedEntry(taskId: string, from: TaskStatus, to: TaskStatus, now: string): AuditEntry {
  return {
    id: nextId("a"),
    task_id: taskId,
    actor_id: CURRENT_USER_ID,
    action: "status_changed",
    detail: `${STATUS_LABEL[from]} → ${STATUS_LABEL[to]}`,
    created_at: now,
  };
}

function timerEntry(taskId: string, action: string, detail: string, now: string): AuditEntry {
  return { id: nextId("a"), task_id: taskId, actor_id: CURRENT_USER_ID, action, detail, created_at: now };
}

/** The task's current open (non-stopped) entry, if any — at most one per task. */
export function openEntryForTask(entries: TimeEntry[], taskId: string): TimeEntry | null {
  return entries.find((e) => e.task_id === taskId && e.status !== "stopped") ?? null;
}

/** The current user's single running entry across the whole board, if any. */
export function runningEntryForUser(entries: TimeEntry[], userId: string): TimeEntry | null {
  return entries.find((e) => e.user_id === userId && e.status === "running") ?? null;
}

/** Elapsed seconds for an entry as of `nowMs`, re-derived client-side per §1.3. */
export function elapsedSeconds(entry: TimeEntry, nowMs: number): number {
  if (entry.status === "running" && entry.last_resumed_at) {
    return entry.accumulated_seconds + Math.max(0, (nowMs - new Date(entry.last_resumed_at).getTime()) / 1000);
  }
  return entry.accumulated_seconds;
}

// ---------------------------------------------------------------------------
// §3.1 Manual (drag-and-drop) status transitions
// ---------------------------------------------------------------------------

const MANUAL_TARGETS: Record<TaskStatus, TaskStatus[]> = {
  backlog: ["todo", "on_hold"],
  todo: ["backlog", "on_hold"],
  on_hold: ["todo", "backlog"],
  in_progress: ["on_hold"],
  completed: [],
};

export function canManualMove(
  state: EngineState,
  taskId: string,
  target: TaskStatus
): { ok: true } | { ok: false; reason: string } {
  const t = state.tasks.find((x) => x.id === taskId);
  if (!t) return { ok: false, reason: "Task not found" };
  if (t.status === target) return { ok: false, reason: "Already there" };
  if (t.status === "completed") {
    return { ok: false, reason: "Completed tasks are terminal — start a new task for further work." };
  }
  if (target === "in_progress") {
    return { ok: false, reason: "In Progress is reached only by pressing Start or Resume." };
  }
  if (target === "completed") {
    return { ok: false, reason: "Completed is reached only by pressing Stop." };
  }
  if (!MANUAL_TARGETS[t.status].includes(target)) {
    if (t.status === "in_progress") {
      return {
        ok: false,
        reason: "In Progress tasks can only be dragged to On Hold — Stop the timer to complete them.",
      };
    }
    return { ok: false, reason: `${STATUS_LABEL[t.status]} can't be moved directly to ${STATUS_LABEL[target]}.` };
  }
  if (t.status === "on_hold" && (target === "todo" || target === "backlog")) {
    const open = openEntryForTask(state.entries, taskId);
    if (open) {
      return { ok: false, reason: "Resume or Stop this task's timer before moving it off On Hold." };
    }
  }
  return { ok: true };
}

export function applyManualMove(state: EngineState, taskId: string, target: TaskStatus, now: string): EngineResult {
  const check = canManualMove(state, taskId, target);
  if (!check.ok) return check;

  const task = state.tasks.find((t) => t.id === taskId)!;
  let entries = state.entries;
  let audit = state.audit;

  // In Progress -> On Hold auto-pauses a running entry *before* recording
  // the status change (design doc §3.1 row for In Progress -> On Hold).
  if (task.status === "in_progress" && target === "on_hold") {
    const open = openEntryForTask(entries, taskId);
    if (open && open.status === "running") {
      const banked = elapsedSeconds(open, new Date(now).getTime());
      entries = entries.map((e) =>
        e.id === open.id ? { ...e, status: "paused", accumulated_seconds: banked, last_resumed_at: null } : e
      );
      audit = [...audit, timerEntry(taskId, "timer_paused", "Paused timer (auto — moved to On Hold)", now)];
    }
  }

  audit = [...audit, statusChangedEntry(taskId, task.status, target, now)];
  const tasks = state.tasks.map((t) => (t.id === taskId ? { ...t, status: target, updated_at: now } : t));

  return { ok: true, state: { ...state, tasks, entries, audit } };
}

// ---------------------------------------------------------------------------
// §3.2 Timer-driven transitions
// ---------------------------------------------------------------------------

export function canStart(state: EngineState, taskId: string): { ok: true } | { ok: false; reason: string } {
  const task = state.tasks.find((t) => t.id === taskId);
  if (!task) return { ok: false, reason: "Task not found" };
  if (task.status !== "todo" && task.status !== "on_hold") {
    return { ok: false, reason: "Start only works from To Do or On Hold." };
  }
  if (openEntryForTask(state.entries, taskId)) {
    return { ok: false, reason: "This task already has a timer entry — use Resume instead." };
  }
  const running = runningEntryForUser(state.entries, CURRENT_USER_ID);
  if (running) {
    const runningTask = state.tasks.find((t) => t.id === running.task_id);
    return {
      ok: false,
      reason: `Pause "${runningTask?.title ?? "your other task"}" first — only one timer can run at a time.`,
    };
  }
  return { ok: true };
}

export function applyStart(state: EngineState, taskId: string, now: string): EngineResult {
  const check = canStart(state, taskId);
  if (!check.ok) return check;

  const task = state.tasks.find((t) => t.id === taskId)!;
  const entry: TimeEntry = {
    id: nextId("e"),
    task_id: taskId,
    user_id: CURRENT_USER_ID,
    status: "running",
    started_at: now,
    last_resumed_at: now,
    accumulated_seconds: 0,
    ended_at: null,
    elapsed_seconds: 0,
  };

  const audit = [
    ...state.audit,
    statusChangedEntry(taskId, task.status, "in_progress", now),
    timerEntry(taskId, "timer_started", "Started timer", now),
  ];
  const tasks = state.tasks.map((t) => (t.id === taskId ? { ...t, status: "in_progress" as const, updated_at: now } : t));

  return { ok: true, state: { ...state, tasks, entries: [...state.entries, entry], audit } };
}

export function canPause(state: EngineState, entryId: string): { ok: true } | { ok: false; reason: string } {
  const entry = state.entries.find((e) => e.id === entryId);
  if (!entry) return { ok: false, reason: "Timer entry not found" };
  if (entry.status !== "running") return { ok: false, reason: "Only a running timer can be paused." };
  return { ok: true };
}

export function applyPause(state: EngineState, entryId: string, now: string): EngineResult {
  const check = canPause(state, entryId);
  if (!check.ok) return check;

  const entry = state.entries.find((e) => e.id === entryId)!;
  const banked = elapsedSeconds(entry, new Date(now).getTime());
  const entries = state.entries.map((e) =>
    e.id === entryId ? { ...e, status: "paused" as const, accumulated_seconds: banked, last_resumed_at: null } : e
  );
  const audit = [...state.audit, timerEntry(entry.task_id, "timer_paused", "Paused timer", now)];

  return { ok: true, state: { ...state, entries, audit } };
}

export function canResume(state: EngineState, entryId: string): { ok: true } | { ok: false; reason: string } {
  const entry = state.entries.find((e) => e.id === entryId);
  if (!entry) return { ok: false, reason: "Timer entry not found" };
  if (entry.status !== "paused") return { ok: false, reason: "Only a paused timer can be resumed." };
  const running = runningEntryForUser(state.entries, CURRENT_USER_ID);
  if (running && running.id !== entryId) {
    const runningTask = state.tasks.find((t) => t.id === running.task_id);
    return {
      ok: false,
      reason: `Pause "${runningTask?.title ?? "your other task"}" first — only one timer can run at a time.`,
    };
  }
  return { ok: true };
}

export function applyResume(state: EngineState, entryId: string, now: string): EngineResult {
  const check = canResume(state, entryId);
  if (!check.ok) return check;

  const entry = state.entries.find((e) => e.id === entryId)!;
  const task = state.tasks.find((t) => t.id === entry.task_id)!;

  let audit = state.audit;
  let tasks = state.tasks;
  if (task.status === "on_hold") {
    audit = [...audit, statusChangedEntry(task.id, "on_hold", "in_progress", now)];
    tasks = tasks.map((t) => (t.id === task.id ? { ...t, status: "in_progress" as const, updated_at: now } : t));
  }
  audit = [...audit, timerEntry(entry.task_id, "timer_resumed", "Resumed timer", now)];

  const entries = state.entries.map((e) =>
    e.id === entryId ? { ...e, status: "running" as const, last_resumed_at: now } : e
  );

  return { ok: true, state: { ...state, tasks, entries, audit } };
}

export function canStop(state: EngineState, entryId: string): { ok: true } | { ok: false; reason: string } {
  const entry = state.entries.find((e) => e.id === entryId);
  if (!entry) return { ok: false, reason: "Timer entry not found" };
  if (entry.status === "stopped") return { ok: false, reason: "This timer has already been stopped." };
  return { ok: true };
}

export function applyStop(state: EngineState, entryId: string, now: string): EngineResult {
  const check = canStop(state, entryId);
  if (!check.ok) return check;

  const entry = state.entries.find((e) => e.id === entryId)!;
  const task = state.tasks.find((t) => t.id === entry.task_id)!;
  const banked = elapsedSeconds(entry, new Date(now).getTime());

  const entries = state.entries.map((e) =>
    e.id === entryId
      ? { ...e, status: "stopped" as const, accumulated_seconds: banked, last_resumed_at: null, ended_at: now }
      : e
  );
  const audit = [
    ...state.audit,
    statusChangedEntry(task.id, task.status, "completed", now),
    timerEntry(task.id, "timer_stopped", "Stopped timer — task completed", now),
  ];
  const tasks = state.tasks.map((t) =>
    t.id === task.id ? { ...t, status: "completed" as const, completed_at: now, updated_at: now } : t
  );

  return { ok: true, state: { ...state, tasks, entries, audit } };
}

export function addComment(state: EngineState, taskId: string, body: string, now: string): EngineResult {
  const trimmed = body.trim();
  if (!trimmed) return { ok: false, reason: "Comment can't be empty." };
  const comment: Comment = { id: nextId("c"), task_id: taskId, author_id: CURRENT_USER_ID, body: trimmed, created_at: now };
  const audit = [
    ...state.audit,
    timerEntry(taskId, "commented", trimmed.length > 120 ? `${trimmed.slice(0, 120)}…` : trimmed, now),
  ];
  return { ok: true, state: { ...state, comments: [...state.comments, comment], audit } };
}

/** Which of the 5 columns this task could legally be dropped into right now. */
export function validDropTargets(state: EngineState, taskId: string): Set<TaskStatus> {
  const targets = new Set<TaskStatus>();
  (Object.keys(MANUAL_TARGETS) as TaskStatus[]).forEach((status) => {
    if (canManualMove(state, taskId, status).ok) targets.add(status);
  });
  return targets;
}
