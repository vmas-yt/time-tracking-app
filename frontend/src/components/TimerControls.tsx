"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Task, TimeEntry } from "@/lib/types";

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

interface TimerControlsProps {
  task: Task;
  openEntries: TimeEntry[];
  onChange: () => void;
}

export function TimerControls({ task, openEntries, onChange }: TimerControlsProps) {
  const ownEntry = openEntries.find((e) => e.task_id === task.id) ?? null;
  const runningElsewhere = openEntries.some((e) => e.status === "running" && e.task_id !== task.id);

  const [elapsed, setElapsed] = useState(ownEntry?.elapsed_seconds ?? 0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setElapsed(ownEntry?.elapsed_seconds ?? 0);
    if (!ownEntry || ownEntry.status !== "running") return;
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ownEntry?.id, ownEntry?.status, ownEntry?.elapsed_seconds]);

  const guard = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      onChange();
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(false);
    }
  };

  if (!ownEntry) {
    if (task.status !== "todo" && task.status !== "on_hold") return null;
    return (
      <button
        className="timer-btn timer-btn--start"
        disabled={busy || runningElsewhere}
        title={runningElsewhere ? "Another timer is already running" : undefined}
        onClick={() => guard(() => api.startTimer(task.id))}
      >
        ▶ Start
      </button>
    );
  }

  return (
    <div className="timer-controls">
      <span className="timer-display">{formatDuration(elapsed)}</span>
      {ownEntry.status === "running" ? (
        <button className="timer-btn" disabled={busy} onClick={() => guard(() => api.pauseTimer(ownEntry.id))}>
          ⏸ Pause
        </button>
      ) : (
        <button
          className="timer-btn"
          disabled={busy || runningElsewhere}
          title={runningElsewhere ? "Another timer is already running" : undefined}
          onClick={() => guard(() => api.resumeTimer(ownEntry.id))}
        >
          ▶ Resume
        </button>
      )}
      <button
        className="timer-btn timer-btn--stop"
        disabled={busy}
        onClick={() => guard(() => api.stopTimer(ownEntry.id))}
      >
        ■ Stop
      </button>
    </div>
  );
}
