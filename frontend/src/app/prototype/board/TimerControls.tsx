"use client";

import { useEffect, useRef, useState } from "react";
import type { Task } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { canResume, canStart, elapsedSeconds, openEntryForTask } from "@/prototype/board/engine";
import { formatDuration } from "@/prototype/board/format";
import { usePrototypeBoard } from "@/prototype/board/store";

function PlayIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}
function PauseIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
    </svg>
  );
}
function StopIcon() {
  return (
    <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <rect x="4" y="4" width="16" height="16" rx="2" />
    </svg>
  );
}
function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

interface TimerControlsProps {
  task: Task;
  size?: "sm" | "md";
}

/**
 * Renders exactly what docs/design/kanban-timer-design.md §3 allows for a
 * task's current state: Start (To Do/On Hold, no open entry), Pause (only
 * the running entry), Resume (only a paused entry), Stop (terminal, always
 * available on an open entry, two-step confirm since it can't be undone).
 */
export function TimerControls({ task, size = "sm" }: TimerControlsProps) {
  const board = usePrototypeBoard();
  const engineState = { tasks: board.tasks, entries: board.entries, audit: board.audit, comments: board.comments };
  const ownEntry = openEntryForTask(board.entries, task.id);

  // Seeded elapsed time depends on Date.now(), which differs between the
  // server-rendered HTML and the client's first paint — start at null (same
  // on server and client) and fill in the real value only after mount so
  // React never sees a hydration mismatch on this text node.
  const [seconds, setSeconds] = useState<number | null>(null);
  const [confirmingStop, setConfirmingStop] = useState(false);
  const confirmTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!ownEntry) return;
    const update = () => setSeconds(elapsedSeconds(ownEntry, Date.now()));
    update();
    if (ownEntry.status !== "running") return;
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ownEntry?.id, ownEntry?.status, ownEntry?.accumulated_seconds]);

  useEffect(
    () => () => {
      if (confirmTimeout.current) clearTimeout(confirmTimeout.current);
    },
    []
  );

  const requestStop = (entryId: string) => {
    if (!confirmingStop) {
      setConfirmingStop(true);
      confirmTimeout.current = setTimeout(() => setConfirmingStop(false), 4000);
      return;
    }
    if (confirmTimeout.current) clearTimeout(confirmTimeout.current);
    setConfirmingStop(false);
    board.stop(entryId);
  };

  if (task.status === "completed") {
    const stoppedEntry = board.entries.find((e) => e.task_id === task.id && e.status === "stopped");
    return (
      <div className="flex items-center gap-1.5 text-xs font-semibold text-positive-deep">
        <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary-pale text-positive-deep">
          <CheckIcon />
        </span>
        Completed
        {stoppedEntry && <span className="font-mono text-mute">· {formatDuration(stoppedEntry.accumulated_seconds)}</span>}
      </div>
    );
  }

  if (!ownEntry) {
    if (task.status !== "todo" && task.status !== "on_hold") return null;
    const check = canStart(engineState, task.id);
    return (
      <div className="flex flex-col items-start gap-1">
        <Button
          size={size}
          variant="primary"
          disabled={!check.ok}
          onClick={() => board.start(task.id)}
          className="shadow-none"
        >
          <PlayIcon /> Start
        </Button>
        {!check.ok && <span className="text-[11px] leading-tight text-mute">{check.reason}</span>}
      </div>
    );
  }

  const displaySeconds = seconds ?? ownEntry.accumulated_seconds;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span
        className={`flex items-center gap-1.5 rounded-lg bg-canvas-soft px-2 py-1 font-mono text-xs tabular-nums text-ink ${
          ownEntry.status === "running" ? "" : "opacity-70"
        }`}
      >
        {ownEntry.status === "running" && (
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-positive opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-positive" />
          </span>
        )}
        {formatDuration(displaySeconds)}
      </span>

      {ownEntry.status === "running" ? (
        <Button size={size} variant="secondary" onClick={() => board.pause(ownEntry.id)}>
          <PauseIcon /> Pause
        </Button>
      ) : (
        (() => {
          const check = canResume(engineState, ownEntry.id);
          return (
            <div className="flex flex-col items-start gap-1">
              <Button size={size} variant="primary" disabled={!check.ok} onClick={() => board.resume(ownEntry.id)}>
                <PlayIcon /> Resume
              </Button>
              {!check.ok && <span className="text-[11px] leading-tight text-mute">{check.reason}</span>}
            </div>
          );
        })()
      )}

      <Button
        size={size}
        variant="danger"
        onClick={() => requestStop(ownEntry.id)}
        title={confirmingStop ? "Click again to confirm — this can't be undone" : "Stop is irreversible"}
        className={confirmingStop ? "animate-pulse" : undefined}
      >
        <StopIcon /> {confirmingStop ? "Confirm Stop?" : "Stop"}
      </Button>
    </div>
  );
}
