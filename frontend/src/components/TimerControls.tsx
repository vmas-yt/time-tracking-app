"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { TimeEntry } from "@/lib/types";

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

interface TimerControlsProps {
  taskId: string;
  activeEntry: TimeEntry | null;
  onChange: (entry: TimeEntry | null) => void;
}

export function TimerControls({ taskId, activeEntry, onChange }: TimerControlsProps) {
  const [elapsed, setElapsed] = useState(activeEntry?.elapsed_seconds ?? 0);
  const [busy, setBusy] = useState(false);

  const isForThisTask = activeEntry?.task_id === taskId;

  useEffect(() => {
    setElapsed(activeEntry?.elapsed_seconds ?? 0);
    if (!activeEntry || activeEntry.status !== "running") return;
    const id = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(id);
  }, [activeEntry]);

  const guard = async (fn: () => Promise<TimeEntry | null>) => {
    setBusy(true);
    try {
      onChange(await fn());
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(false);
    }
  };

  if (!activeEntry && !isForThisTask) {
    return (
      <button
        className="timer-btn timer-btn--start"
        disabled={busy || (!!activeEntry && !isForThisTask)}
        onClick={() => guard(() => api.startTimer(taskId))}
      >
        ▶ Start
      </button>
    );
  }

  if (!isForThisTask) {
    return <span className="timer-disabled">Another timer is running</span>;
  }

  return (
    <div className="timer-controls">
      <span className="timer-display">{formatDuration(elapsed)}</span>
      {activeEntry!.status === "running" ? (
        <button className="timer-btn" disabled={busy} onClick={() => guard(() => api.pauseTimer(activeEntry!.id))}>
          ⏸ Pause
        </button>
      ) : (
        <button className="timer-btn" disabled={busy} onClick={() => guard(() => api.resumeTimer(activeEntry!.id))}>
          ▶ Resume
        </button>
      )}
      <button
        className="timer-btn timer-btn--stop"
        disabled={busy}
        onClick={() => guard(async () => { await api.stopTimer(activeEntry!.id); return null; })}
      >
        ■ Stop
      </button>
    </div>
  );
}
