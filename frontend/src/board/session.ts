"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Task, TimeEntry } from "@/lib/types";
import { canEditTask as canEditTaskPure } from "./engine";

export interface SessionToast {
  id: number;
  tone: "error" | "info";
  message: string;
}

interface UseTimerSessionOptions {
  /** Called after every successful mutation (start/pause/resume/stop/move/
   * create/etc.) so the caller can refresh whatever task data it owns —
   * the full board's task list, or a single task's detail fetch. */
  onMutated?: () => void;
}

/**
 * Owns "what timers of mine are open, and can I mutate this task" — the
 * slice of board state that's the same whether you're looking at the full
 * Kanban board or a single task's detail page. Both `board/store.tsx` (the
 * board) and `app/tasks/[id]/page.tsx` (standalone detail view) use this
 * instead of duplicating fetch/guard/toast logic. "Who am I" itself comes
 * from the shared `AuthContext` (`@/lib/auth`) rather than a redundant
 * `api.me()` call here — `AuthGate` already guarantees a valid session by
 * the time any page using this hook renders.
 */
export function useTimerSession(options: UseTimerSessionOptions = {}) {
  const { onMutated } = options;
  const { user: currentUser } = useAuth();
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [toast, setToast] = useState<SessionToast | null>(null);
  const [pendingKeys, setPendingKeys] = useState<Set<string>>(new Set());
  const toastCounter = useRef(0);

  const refreshEntries = useCallback(async () => {
    try {
      setEntries(await api.listOpenTimers());
    } catch {
      // Non-fatal — keep the last-known entries rather than blanking the
      // timer UI on a transient refresh failure.
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setSessionLoading(true);
      setSessionError(null);
      try {
        const openEntries = await api.listOpenTimers();
        if (cancelled) return;
        setEntries(openEntries);
      } catch (err) {
        if (!cancelled) setSessionError(err instanceof Error ? err.message : "Could not load your session");
      } finally {
        if (!cancelled) setSessionLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const notifyError = useCallback((message: string) => {
    toastCounter.current += 1;
    setToast({ id: toastCounter.current, tone: "error", message });
  }, []);

  const dismissToast = useCallback(() => setToast(null), []);

  /** Runs a mutation with a per-key busy flag (disable just the affected
   * task's controls, not the whole board), surfaces any failure — 403
   * (not authorized), 409 (illegal transition / already-open timer / race
   * with another tab), or otherwise — as a visible toast, and refreshes
   * open timers + whatever the caller depends on afterward. */
  const runMutation = useCallback(
    async <T,>(key: string, fn: () => Promise<T>): Promise<T | null> => {
      setPendingKeys((prev) => new Set(prev).add(key));
      try {
        const result = await fn();
        await refreshEntries();
        onMutated?.();
        return result;
      } catch (err) {
        notifyError(err instanceof Error ? err.message : "Something went wrong — please try again.");
        return null;
      } finally {
        setPendingKeys((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    },
    [refreshEntries, onMutated, notifyError]
  );

  const start = useCallback((taskId: string) => runMutation(taskId, () => api.startTimer(taskId)), [runMutation]);
  const pause = useCallback(
    (entry: TimeEntry) => runMutation(entry.task_id, () => api.pauseTimer(entry.id)),
    [runMutation]
  );
  const resume = useCallback(
    (entry: TimeEntry) => runMutation(entry.task_id, () => api.resumeTimer(entry.id)),
    [runMutation]
  );
  const stop = useCallback(
    (entry: TimeEntry) => runMutation(entry.task_id, () => api.stopTimer(entry.id)),
    [runMutation]
  );

  const canEditTask = useCallback((task: Task) => canEditTaskPure(currentUser, task), [currentUser]);
  const isPending = useCallback((key: string) => pendingKeys.has(key), [pendingKeys]);

  return {
    currentUser,
    entries,
    sessionLoading,
    sessionError,
    toast,
    dismissToast,
    notifyError,
    isPending,
    canEditTask,
    start,
    pause,
    resume,
    stop,
    refreshEntries,
    runMutation,
  };
}
