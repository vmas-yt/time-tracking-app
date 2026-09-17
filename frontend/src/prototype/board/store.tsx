"use client";

import { createContext, useContext, useMemo, useReducer } from "react";
import type { ReactNode } from "react";
import type { BoardConfig, SwimlaneField, Task, TaskStatus, User } from "@/lib/types";
import {
  AUDIT_ENTRIES,
  COMMENTS,
  CURRENT_USER_ID,
  DEFAULT_BOARD_CONFIG,
  TASKS,
  TIME_ENTRIES,
  USERS,
} from "./seed";
import type { EngineState } from "./engine";
import { addComment, applyManualMove, applyPause, applyResume, applyStart, applyStop } from "./engine";

interface Toast {
  id: number;
  tone: "error" | "info";
  message: string;
}

interface State extends EngineState {
  users: User[];
  boardConfig: BoardConfig;
  selectedTaskId: string | null;
  toast: Toast | null;
}

type Action =
  | { type: "START"; taskId: string }
  | { type: "PAUSE"; entryId: string }
  | { type: "RESUME"; entryId: string }
  | { type: "STOP"; entryId: string }
  | { type: "MOVE"; taskId: string; target: TaskStatus }
  | { type: "ADD_COMMENT"; taskId: string; body: string }
  | { type: "SET_SWIMLANE"; field: SwimlaneField }
  | { type: "SELECT_TASK"; taskId: string | null }
  | { type: "DISMISS_TOAST" };

let toastCounter = 0;

function withResult(state: State, result: { ok: true; state: EngineState } | { ok: false; reason: string }): State {
  if (!result.ok) {
    toastCounter += 1;
    return { ...state, toast: { id: toastCounter, tone: "error", message: result.reason } };
  }
  return { ...state, ...result.state, toast: null };
}

function reducer(state: State, action: Action): State {
  const now = new Date().toISOString();
  switch (action.type) {
    case "START":
      return withResult(state, applyStart(state, action.taskId, now));
    case "PAUSE":
      return withResult(state, applyPause(state, action.entryId, now));
    case "RESUME":
      return withResult(state, applyResume(state, action.entryId, now));
    case "STOP":
      return withResult(state, applyStop(state, action.entryId, now));
    case "MOVE":
      return withResult(state, applyManualMove(state, action.taskId, action.target, now));
    case "ADD_COMMENT":
      return withResult(state, addComment(state, action.taskId, action.body, now));
    case "SET_SWIMLANE":
      return { ...state, boardConfig: { swimlane_field: action.field, updated_at: now } };
    case "SELECT_TASK":
      return { ...state, selectedTaskId: action.taskId };
    case "DISMISS_TOAST":
      return { ...state, toast: null };
    default:
      return state;
  }
}

function initialState(): State {
  return {
    tasks: TASKS,
    entries: TIME_ENTRIES,
    audit: AUDIT_ENTRIES,
    comments: COMMENTS,
    users: USERS,
    boardConfig: DEFAULT_BOARD_CONFIG,
    selectedTaskId: null,
    toast: null,
  };
}

interface BoardApi {
  tasks: Task[];
  users: User[];
  boardConfig: BoardConfig;
  selectedTaskId: string | null;
  toast: Toast | null;
  currentUserId: string;
  entries: State["entries"];
  comments: State["comments"];
  audit: State["audit"];
  start: (taskId: string) => void;
  pause: (entryId: string) => void;
  resume: (entryId: string) => void;
  stop: (entryId: string) => void;
  move: (taskId: string, target: TaskStatus) => void;
  comment: (taskId: string, body: string) => void;
  setSwimlaneField: (field: SwimlaneField) => void;
  selectTask: (taskId: string | null) => void;
  dismissToast: () => void;
}

const BoardContext = createContext<BoardApi | null>(null);

export function PrototypeBoardProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);

  const api = useMemo<BoardApi>(
    () => ({
      tasks: state.tasks,
      users: state.users,
      boardConfig: state.boardConfig,
      selectedTaskId: state.selectedTaskId,
      toast: state.toast,
      currentUserId: CURRENT_USER_ID,
      entries: state.entries,
      comments: state.comments,
      audit: state.audit,
      start: (taskId) => dispatch({ type: "START", taskId }),
      pause: (entryId) => dispatch({ type: "PAUSE", entryId }),
      resume: (entryId) => dispatch({ type: "RESUME", entryId }),
      stop: (entryId) => dispatch({ type: "STOP", entryId }),
      move: (taskId, target) => dispatch({ type: "MOVE", taskId, target }),
      comment: (taskId, body) => dispatch({ type: "ADD_COMMENT", taskId, body }),
      setSwimlaneField: (field) => dispatch({ type: "SET_SWIMLANE", field }),
      selectTask: (taskId) => dispatch({ type: "SELECT_TASK", taskId }),
      dismissToast: () => dispatch({ type: "DISMISS_TOAST" }),
    }),
    [state]
  );

  return <BoardContext.Provider value={api}>{children}</BoardContext.Provider>;
}

export function usePrototypeBoard(): BoardApi {
  const ctx = useContext(BoardContext);
  if (!ctx) throw new Error("usePrototypeBoard must be used within PrototypeBoardProvider");
  return ctx;
}
