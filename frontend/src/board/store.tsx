"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import type { BoardConfig, SwimlaneField, Task, TaskCategory, TaskPriority, TaskStatus, TaskType, TimeEntry, User } from "@/lib/types";
import { useTimerSession } from "./session";
import type { SessionToast } from "./session";

export interface CreateTaskInput {
  title: string;
  description?: string;
  task_type?: TaskType;
  category: TaskCategory;
  category_other_text?: string;
  priority?: TaskPriority;
  assignee_id?: string | null;
}

interface BoardApi {
  loading: boolean;
  error: string | null;
  projectId: string | null;
  tasks: Task[];
  users: User[];
  managers: User[];
  boardConfig: BoardConfig;
  currentUser: User | null;
  currentUserId: string;
  entries: TimeEntry[];
  toast: SessionToast | null;
  dismissToast: () => void;
  isPending: (key: string) => boolean;
  canEditTask: (task: Task) => boolean;
  canManageBoardConfig: boolean;
  selectedTaskId: string | null;
  selectTask: (taskId: string | null) => void;
  managerFilter: string | null;
  setManagerFilter: (managerId: string | null) => void;
  start: (taskId: string) => void;
  pause: (entry: TimeEntry) => void;
  resume: (entry: TimeEntry) => void;
  stop: (entry: TimeEntry) => void;
  move: (taskId: string, target: TaskStatus) => void;
  createTask: (input: CreateTaskInput) => Promise<Task | null>;
  setSwimlaneField: (field: SwimlaneField) => void;
  refresh: () => void;
}

const BoardContext = createContext<BoardApi | null>(null);

export function BoardProvider({ children, projectId = null }: { children: ReactNode; projectId?: string | null }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [boardConfig, setBoardConfig] = useState<BoardConfig>({ swimlane_field: "assignee", updated_at: "" });
  const [boardLoading, setBoardLoading] = useState(true);
  const [boardError, setBoardError] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [managerFilter, setManagerFilter] = useState<string | null>(null);

  const listParams = useCallback(
    () => ({
      ...(projectId ? { projectId } : {}),
      ...(managerFilter ? { managerId: managerFilter } : {}),
    }),
    [projectId, managerFilter]
  );

  const refreshTasks = useCallback(async () => {
    try {
      setTasks(await api.listTasks(listParams()));
    } catch (err) {
      // A failed background refresh after a mutation shouldn't blank the
      // board — the mutation's own success/failure is already toasted by
      // the session layer. Log for diagnostics only.
      console.error("Failed to refresh tasks", err);
    }
  }, [listParams]);

  const session = useTimerSession({ onMutated: refreshTasks });

  const loadBoard = useCallback(async () => {
    setBoardLoading(true);
    setBoardError(null);
    try {
      const [taskList, userList, config] = await Promise.all([
        api.listTasks(listParams()),
        api.listUsers(),
        api.getBoardConfig(),
      ]);
      setTasks(taskList);
      setUsers(userList);
      setBoardConfig(config);
    } catch (err) {
      setBoardError(err instanceof Error ? err.message : "Could not load the board");
    } finally {
      setBoardLoading(false);
    }
  }, [listParams]);

  useEffect(() => {
    loadBoard();
  }, [loadBoard]);

  const move = useCallback(
    (taskId: string, target: TaskStatus) => {
      session.runMutation(taskId, () => api.updateTask(taskId, { status: target }));
    },
    [session]
  );

  const createTask = useCallback(
    (input: CreateTaskInput) =>
      session.runMutation("__create_task__", () =>
        api.createTask({ project_id: projectId, ...input })
      ),
    [session, projectId]
  );

  const setSwimlaneField = useCallback(
    async (field: SwimlaneField) => {
      const updated = await session.runMutation("__swimlane__", () => api.updateBoardConfig(field));
      if (updated) setBoardConfig(updated);
    },
    [session]
  );

  const refresh = useCallback(() => {
    loadBoard();
    session.refreshEntries();
  }, [loadBoard, session]);

  const managers = useMemo(() => users.filter((u) => u.role === "manager"), [users]);
  const canManageBoardConfig = session.currentUser?.role === "admin";

  const api_: BoardApi = useMemo(
    () => ({
      loading: boardLoading || session.sessionLoading,
      error: boardError ?? session.sessionError,
      projectId,
      tasks,
      users,
      managers,
      boardConfig,
      currentUser: session.currentUser,
      currentUserId: session.currentUser?.id ?? "",
      entries: session.entries,
      toast: session.toast,
      dismissToast: session.dismissToast,
      isPending: session.isPending,
      canEditTask: session.canEditTask,
      canManageBoardConfig,
      selectedTaskId,
      selectTask: setSelectedTaskId,
      managerFilter,
      setManagerFilter,
      start: session.start,
      pause: session.pause,
      resume: session.resume,
      stop: session.stop,
      move,
      createTask,
      setSwimlaneField,
      refresh,
    }),
    [
      boardLoading,
      session.sessionLoading,
      boardError,
      session.sessionError,
      projectId,
      tasks,
      users,
      managers,
      boardConfig,
      session.currentUser,
      session.entries,
      session.toast,
      session.dismissToast,
      session.isPending,
      session.canEditTask,
      canManageBoardConfig,
      selectedTaskId,
      managerFilter,
      session.start,
      session.pause,
      session.resume,
      session.stop,
      move,
      createTask,
      setSwimlaneField,
      refresh,
    ]
  );

  return <BoardContext.Provider value={api_}>{children}</BoardContext.Provider>;
}

export function useBoard(): BoardApi {
  const ctx = useContext(BoardContext);
  if (!ctx) throw new Error("useBoard must be used within BoardProvider");
  return ctx;
}
