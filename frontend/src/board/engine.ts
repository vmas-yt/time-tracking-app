import type { Task, TaskStatus, TimeEntry, User } from "@/lib/types";

// ---------------------------------------------------------------------------
// Pure client-side guard logic mirroring docs/design/kanban-timer-design.md
// §3. This is UI-only "should I show/enable this control, and with what
// explanation" logic — the backend is the actual source of truth and
// re-validates every mutation server-side (see backend/app/services/timer.py
// and services/authz.py); a real 409/403 from the API is still surfaced as a
// toast even if these guards say "ok" (e.g. a race with another tab, or
// stale board data). No I/O, no fetches, no dummy data — just derivations
// over whatever tasks/entries the caller already has in state.
// ---------------------------------------------------------------------------

export interface EngineState {
  tasks: Task[];
  entries: TimeEntry[];
}

const STATUS_LABEL: Record<TaskStatus, string> = {
  backlog: "Backlog",
  todo: "To Do",
  in_progress: "In Progress",
  on_hold: "On Hold",
  completed: "Completed",
};

/** The task's current open (non-stopped) entry, if any — at most one per task. */
export function openEntryForTask(entries: TimeEntry[], taskId: string): TimeEntry | null {
  return entries.find((e) => e.task_id === taskId && e.status !== "stopped") ?? null;
}

/** The given user's single running entry across the whole board, if any. */
export function runningEntryForUser(entries: TimeEntry[], userId: string): TimeEntry | null {
  return entries.find((e) => e.user_id === userId && e.status === "running") ?? null;
}

/** Elapsed seconds for an entry as of `nowMs`, re-derived client-side per §1.3 —
 * the API's `elapsed_seconds` is only accurate as of the moment it responded. */
export function elapsedSeconds(entry: TimeEntry, nowMs: number): number {
  if (entry.status === "running" && entry.last_resumed_at) {
    return entry.accumulated_seconds + Math.max(0, (nowMs - new Date(entry.last_resumed_at).getTime()) / 1000);
  }
  return entry.accumulated_seconds;
}

/** Assignee, creator, or admin may edit a task or drive its timer — mirrors
 * `services/authz.can_edit_task` exactly (managers are deliberately
 * excluded: review-only per the PRD). Used to decide whether to render
 * interactive controls at all, so the UI doesn't invite an action the
 * backend will 403. */
export function canEditTask(currentUser: Pick<User, "id" | "role"> | null, task: Task): boolean {
  if (!currentUser) return false;
  if (currentUser.role === "admin") return true;
  return currentUser.id === task.assignee_id || currentUser.id === task.created_by_id;
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

/** Which of the 5 columns this task could legally be dropped into right now. */
export function validDropTargets(state: EngineState, taskId: string): Set<TaskStatus> {
  const targets = new Set<TaskStatus>();
  (Object.keys(MANUAL_TARGETS) as TaskStatus[]).forEach((status) => {
    if (canManualMove(state, taskId, status).ok) targets.add(status);
  });
  return targets;
}

// ---------------------------------------------------------------------------
// §3.2 Timer-driven transitions
// ---------------------------------------------------------------------------

export function canStart(
  state: EngineState,
  taskId: string,
  currentUserId: string
): { ok: true } | { ok: false; reason: string } {
  const task = state.tasks.find((t) => t.id === taskId);
  if (!task) return { ok: false, reason: "Task not found" };
  // Tightened to assignee-only (backend design doc §9.1): starting a timer
  // always attributes the new entry to whoever clicks Start, so unlike
  // canEditTask (assignee/creator/admin), a task's creator or an admin must
  // NOT see an enabled Start button on someone else's task — the backend
  // 403s them too, and showing it here would only invite a doomed request.
  if (currentUserId !== task.assignee_id) {
    return { ok: false, reason: "Only the task's assignee can start its timer." };
  }
  if (task.status !== "todo" && task.status !== "on_hold") {
    return { ok: false, reason: "Start only works from To Do or On Hold." };
  }
  if (openEntryForTask(state.entries, taskId)) {
    return { ok: false, reason: "This task already has a timer entry — use Resume instead." };
  }
  const running = runningEntryForUser(state.entries, currentUserId);
  if (running) {
    const runningTask = state.tasks.find((t) => t.id === running.task_id);
    return {
      ok: false,
      reason: `Pause "${runningTask?.title ?? "your other task"}" first — only one timer can run at a time.`,
    };
  }
  return { ok: true };
}

export function canPause(state: EngineState, entryId: string): { ok: true } | { ok: false; reason: string } {
  const entry = state.entries.find((e) => e.id === entryId);
  if (!entry) return { ok: false, reason: "Timer entry not found" };
  if (entry.status !== "running") return { ok: false, reason: "Only a running timer can be paused." };
  return { ok: true };
}

export function canResume(
  state: EngineState,
  entryId: string,
  currentUserId: string
): { ok: true } | { ok: false; reason: string } {
  const entry = state.entries.find((e) => e.id === entryId);
  if (!entry) return { ok: false, reason: "Timer entry not found" };
  if (entry.status !== "paused") return { ok: false, reason: "Only a paused timer can be resumed." };
  const running = runningEntryForUser(state.entries, currentUserId);
  if (running && running.id !== entryId) {
    const runningTask = state.tasks.find((t) => t.id === running.task_id);
    return {
      ok: false,
      reason: `Pause "${runningTask?.title ?? "your other task"}" first — only one timer can run at a time.`,
    };
  }
  return { ok: true };
}

export function canStop(state: EngineState, entryId: string): { ok: true } | { ok: false; reason: string } {
  const entry = state.entries.find((e) => e.id === entryId);
  if (!entry) return { ok: false, reason: "Timer entry not found" };
  if (entry.status === "stopped") return { ok: false, reason: "This timer has already been stopped." };
  return { ok: true };
}
