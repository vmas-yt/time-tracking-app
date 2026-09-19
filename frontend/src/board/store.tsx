"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import type {
  BoardConfig,
  CustomField,
  DropdownOption,
  Project,
  SwimlaneField,
  Task,
  TaskCategory,
  TaskPriority,
  TaskStatus,
  TaskType,
  Team,
  TeamBoardConfig,
  TimeEntry,
  User,
} from "@/lib/types";
import { useTimerSession } from "./session";
import type { SessionToast } from "./session";
import type { ManualLogInput } from "@/lib/types";

export interface CreateTaskInput {
  title: string;
  description?: string;
  task_type?: TaskType;
  category: TaskCategory;
  category_other_text?: string;
  priority?: TaskPriority;
  assignee_id?: string | null;
  project_id?: string | null;
  custom_values?: Record<string, string>;
}

/** `CreateTaskInput` plus the manual-log trio — body of `POST
 * /tasks/manual-log` (create a brand-new task and its first logged time
 * entry in one shot). */
export interface CreateManualTaskInput extends CreateTaskInput, ManualLogInput {}

export interface UpdateTaskInput {
  title?: string;
  description?: string;
  project_id?: string | null;
  assignee_id?: string | null;
  category?: TaskCategory;
  category_other_text?: string;
  priority?: TaskPriority;
  custom_values?: Record<string, string>;
}

interface BoardApi {
  loading: boolean;
  error: string | null;
  projectId: string | null;
  // Round C (docs/design/team-scoped-boards-design.md §6.1) — `?team=<id>`
  // scoping, threaded through exactly like `projectId` above. Fully wired:
  // the task-list filter (§4.4), the per-team board-config fetch/mutate
  // (§4.1/§4.2, see `boardConfig`/`setSwimlaneField` below), and the team
  // switcher UI itself (`BoardScreen.tsx`) all key off this.
  teamId: string | null;
  tasks: Task[];
  users: User[];
  managers: User[];
  // Active teams (`GET /teams`, unfiltered by department) — populates the
  // board's team switcher (§6.1) and the admin swim-lanes screen's per-team
  // table (§6.2).
  teams: Team[];
  projects: Project[];
  customFields: CustomField[];
  categoryOptions: DropdownOption[];
  priorityOptions: DropdownOption[];
  // Round C: the global `BoardConfig` (unscoped view) when `teamId` is null,
  // or the selected team's `TeamBoardConfig` when it isn't (§6.1) — both
  // share `swimlane_field`/`updated_at`/`can_manage`, so every existing
  // reader of `boardConfig.swimlane_field`/`.can_manage` keeps working
  // unchanged regardless of which one is currently loaded.
  boardConfig: BoardConfig | TeamBoardConfig;
  // The board header's effective title when a team is selected: that team's
  // `TeamBoardConfig.board_name` if set, else the team's own `Team.name`
  // (§3). `null` when no team is selected (the unscoped view keeps its
  // generic "Kanban board" title).
  effectiveBoardName: string | null;
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
  createManualTask: (input: CreateManualTaskInput) => Promise<Task | null>;
  logManualTime: (taskId: string, input: ManualLogInput) => Promise<Task | null>;
  updateTask: (taskId: string, input: UpdateTaskInput) => Promise<Task | null>;
  setSwimlaneField: (field: SwimlaneField) => void;
  refresh: () => void;
}

const BoardContext = createContext<BoardApi | null>(null);

export function BoardProvider({
  children,
  projectId = null,
  teamId = null,
}: {
  children: ReactNode;
  projectId?: string | null;
  // Round C — mirrors `projectId` exactly (§6.1); `null`/absent behaves
  // identically to today's unscoped board (no `team_id` filter sent).
  teamId?: string | null;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [customFields, setCustomFields] = useState<CustomField[]>([]);
  const [categoryOptions, setCategoryOptions] = useState<DropdownOption[]>([]);
  const [priorityOptions, setPriorityOptions] = useState<DropdownOption[]>([]);
  const [boardConfig, setBoardConfig] = useState<BoardConfig | TeamBoardConfig>({
    swimlane_field: "assignee",
    updated_at: "",
    can_manage: false,
  });
  const [boardLoading, setBoardLoading] = useState(true);
  const [boardError, setBoardError] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [managerFilter, setManagerFilter] = useState<string | null>(null);

  const listParams = useCallback(
    () => ({
      ...(projectId ? { projectId } : {}),
      ...(teamId ? { teamId } : {}),
      ...(managerFilter ? { managerId: managerFilter } : {}),
    }),
    [projectId, teamId, managerFilter]
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
      const [taskList, userList, teamList, config, projectList, fieldList, categories, priorities] =
        await Promise.all([
          api.listTasks(listParams()),
          api.listUsers(),
          api.listTeams(),
          // Round C (§6.1, §5.3): a selected team's board reads/writes its
          // own `TeamBoardConfig` (`GET /teams/{id}/board-config`), never
          // the global singleton — the unscoped view (`teamId === null`)
          // keeps using the global `GET /admin/board-config` exactly as
          // before.
          teamId ? api.getTeamBoardConfig(teamId) : api.getBoardConfig(),
          api.listProjects(),
          api.listCustomFields(),
          api.listDropdownOptions({ scope: "task_category" }),
          api.listDropdownOptions({ scope: "task_priority" }),
        ]);
      setTasks(taskList);
      setUsers(userList);
      setTeams(teamList);
      setBoardConfig(config);
      setProjects(projectList);
      setCustomFields(fieldList);
      setCategoryOptions(categories);
      setPriorityOptions(priorities);
    } catch (err) {
      setBoardError(err instanceof Error ? err.message : "Could not load the board");
    } finally {
      setBoardLoading(false);
    }
  }, [listParams, teamId]);

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

  const createManualTask = useCallback(
    (input: CreateManualTaskInput) =>
      session.runMutation("__create_task__", () =>
        api.createManualTask({ project_id: projectId, ...input })
      ),
    [session, projectId]
  );

  const logManualTime = useCallback(
    (taskId: string, input: ManualLogInput) =>
      session.runMutation(taskId, () => api.logManualTimeForTask(taskId, input)),
    [session]
  );

  const updateTask = useCallback(
    (taskId: string, input: UpdateTaskInput) => session.runMutation(taskId, () => api.updateTask(taskId, input)),
    [session]
  );

  const setSwimlaneField = useCallback(
    async (field: SwimlaneField) => {
      // Round C (§4.2/§6.1): PATCH the selected team's own config when one is
      // selected, the global singleton otherwise — mirrors `loadBoard`'s read
      // side above so the two never drift onto different endpoints.
      const updated = await session.runMutation("__swimlane__", () =>
        teamId ? api.updateTeamBoardConfig(teamId, { swimlane_field: field }) : api.updateBoardConfig(field)
      );
      if (updated) setBoardConfig(updated);
    },
    [session, teamId]
  );

  const refresh = useCallback(() => {
    loadBoard();
    session.refreshEntries();
  }, [loadBoard, session]);

  const managers = useMemo(() => users.filter((u) => u.role === "manager"), [users]);
  // Round C fix (docs/design/team-scoped-boards-design.md §5.3): read the
  // server-computed `can_manage` field off the fetched `BoardConfig`
  // instead of re-deriving permission from the legacy `role` string. The
  // old `session.currentUser?.role === "admin"` check meant a custom role
  // granted `manage_board_config` (Round B3) couldn't actually use the
  // "Group lanes by" control even though the backend would accept the
  // `PATCH` — `can_manage` is the exact same boolean the backend's own
  // `PATCH` handler checks before its `403`, so this can never drift from
  // what the server actually enforces.
  const canManageBoardConfig = boardConfig.can_manage;

  // Round C (§3, §6.1): effective board title for the selected team — its
  // own `board_name` if set, else its `Team.name` — `null` when unscoped.
  // `"board_name" in boardConfig` narrows the union: only `TeamBoardConfig`
  // carries that field, so this is `null` whenever the global config is the
  // one currently loaded (i.e. `teamId` is null), even before `teams` has
  // resolved.
  const effectiveBoardName = useMemo(() => {
    if (!teamId) return null;
    const configName = "board_name" in boardConfig ? boardConfig.board_name : null;
    return configName ?? teams.find((t) => t.id === teamId)?.name ?? null;
  }, [teamId, boardConfig, teams]);

  const api_: BoardApi = useMemo(
    () => ({
      loading: boardLoading || session.sessionLoading,
      error: boardError ?? session.sessionError,
      projectId,
      teamId,
      tasks,
      users,
      managers,
      teams,
      projects,
      customFields,
      categoryOptions,
      priorityOptions,
      boardConfig,
      effectiveBoardName,
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
      createManualTask,
      logManualTime,
      updateTask,
      setSwimlaneField,
      refresh,
    }),
    [
      boardLoading,
      session.sessionLoading,
      boardError,
      session.sessionError,
      projectId,
      teamId,
      tasks,
      users,
      managers,
      teams,
      projects,
      customFields,
      categoryOptions,
      priorityOptions,
      boardConfig,
      effectiveBoardName,
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
      createManualTask,
      logManualTime,
      updateTask,
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
