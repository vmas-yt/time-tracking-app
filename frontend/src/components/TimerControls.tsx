"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Task, TimeEntry } from "@/lib/types";
import { Button } from "@/components/ui/Button";

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

function PlayIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
      <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
      <rect x="5" y="5" width="14" height="14" rx="1.5" />
    </svg>
  );
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
      <Button
        size="sm"
        variant="primary"
        disabled={busy || runningElsewhere}
        title={runningElsewhere ? "Another timer is already running" : undefined}
        onClick={() => guard(() => api.startTimer(task.id))}
      >
        <PlayIcon /> Start
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-xs tabular-nums text-mute">{formatDuration(elapsed)}</span>
      {ownEntry.status === "running" ? (
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => guard(() => api.pauseTimer(ownEntry.id))}>
          <PauseIcon /> Pause
        </Button>
      ) : (
        <Button
          size="sm"
          variant="primary"
          disabled={busy || runningElsewhere}
          title={runningElsewhere ? "Another timer is already running" : undefined}
          onClick={() => guard(() => api.resumeTimer(ownEntry.id))}
        >
          <PlayIcon /> Resume
        </Button>
      )}
      <Button size="sm" variant="danger" disabled={busy} onClick={() => guard(() => api.stopTimer(ownEntry.id))}>
        <StopIcon /> Stop
      </Button>
    </div>
  );
}
