"use client";

import { useEffect, useRef, useState } from "react";
import type { ManualEntrySettings, ManualLogInput, Task, TimeEntry } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { canResume, canStart, elapsedSeconds, openEntryForTask } from "@/board/engine";
import { formatDuration } from "@/board/format";
import {
  fetchManualEntrySettings,
  todayDateString,
  toDurationMinutes,
  validateManualLog,
  type ManualLogDraft,
} from "@/board/manualLog";
import { ManualLogFields } from "./ManualLogFields";

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
  /** The current user's own open (non-stopped) timer entries, across all
   * their tasks — from `GET /time-entries/open`. Used both to find this
   * task's own entry and to evaluate the "only one running" guard. */
  entries: TimeEntry[];
  currentUserId: string;
  /** Whether the current user may drive this task's timer at all
   * (assignee/creator/admin — see `engine.canEditTask`). If false, no
   * buttons are rendered — a click would just 403. */
  canEdit: boolean;
  isPending: boolean;
  onStart: (taskId: string) => void;
  onPause: (entry: TimeEntry) => void;
  onResume: (entry: TimeEntry) => void;
  onStop: (entry: TimeEntry) => void;
  /** Submits a manual/retroactive entry for this task (same eligibility
   * window as Start: To Do/On Hold, no existing entry). Resolves `true` on
   * success so the modal can close itself; `false`/rejected leaves it open
   * so the user can fix the form — the caller's own toast already surfaces
   * *why* it failed. */
  onManualLog: (taskId: string, input: ManualLogInput) => Promise<boolean>;
  size?: "sm" | "md";
}

/**
 * Renders exactly what docs/design/kanban-timer-design.md §3 allows for a
 * task's current state: Start (To Do/On Hold, no open entry), Pause (only
 * the running entry), Resume (only a paused entry), Stop (terminal, two-step
 * confirm since it can't be undone). All state comes from props so this
 * works identically on the board (via `useBoard`) and the standalone task
 * detail page (via `useTimerSession`).
 */
export function TimerControls({
  task,
  entries,
  currentUserId,
  canEdit,
  isPending,
  onStart,
  onPause,
  onResume,
  onStop,
  onManualLog,
  size = "sm",
}: TimerControlsProps) {
  const engineState = { tasks: [task], entries };
  const ownEntry = openEntryForTask(entries, task.id);

  // Elapsed time depends on Date.now(), which differs between the
  // server-rendered HTML and the client's first paint — start at null (same
  // on server and client) and fill in the real value only after mount so
  // React never sees a hydration mismatch on this text node.
  const [seconds, setSeconds] = useState<number | null>(null);
  const [confirmingStop, setConfirmingStop] = useState(false);
  const confirmTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---- Manual/retroactive time logging (docs/PRD.md) ----------------------
  const [manualOpen, setManualOpen] = useState(false);
  const [manualDraft, setManualDraft] = useState<ManualLogDraft>({
    startDate: todayDateString(),
    completionDate: todayDateString(),
    hours: 0,
    minutes: 0,
  });
  const [manualSettings, setManualSettings] = useState<ManualEntrySettings | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);
  const [manualSubmitting, setManualSubmitting] = useState(false);

  const openManualLog = () => {
    setManualDraft({ startDate: todayDateString(), completionDate: todayDateString(), hours: 0, minutes: 0 });
    setManualError(null);
    setManualOpen(true);
    fetchManualEntrySettings()
      .then(setManualSettings)
      .catch(() => {
        // Non-fatal — the backend still authoritatively validates on submit.
      });
  };

  const submitManualLog = async () => {
    const err = validateManualLog(manualDraft, manualSettings?.max_days_back ?? null);
    if (err) {
      setManualError(err);
      return;
    }
    setManualError(null);
    setManualSubmitting(true);
    const ok = await onManualLog(task.id, {
      start_date: manualDraft.startDate,
      completion_date: manualDraft.completionDate,
      duration_minutes: toDurationMinutes(manualDraft),
    });
    setManualSubmitting(false);
    if (ok) setManualOpen(false);
  };

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

  const requestStop = (entry: TimeEntry) => {
    if (!confirmingStop) {
      setConfirmingStop(true);
      confirmTimeout.current = setTimeout(() => setConfirmingStop(false), 4000);
      return;
    }
    if (confirmTimeout.current) clearTimeout(confirmTimeout.current);
    setConfirmingStop(false);
    onStop(entry);
  };

  if (task.status === "completed") {
    return (
      <div className="flex items-center gap-1.5 text-xs font-semibold text-positive-deep">
        <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary-pale text-positive-deep">
          <CheckIcon />
        </span>
        Completed
        {task.total_logged_seconds > 0 && (
          <span className="font-mono text-mute">· {formatDuration(task.total_logged_seconds)}</span>
        )}
      </div>
    );
  }

  if (!canEdit) {
    // Visible, not a silent no-op: the viewer can see this task (it's on
    // their board) but isn't its assignee/creator/admin, so the backend
    // would 403 on any timer action — don't offer buttons that can't work.
    return <span className="text-[11px] italic text-mute">Only the assignee can control this timer</span>;
  }

  if (!ownEntry) {
    if (task.status !== "todo" && task.status !== "on_hold") {
      // On the compact board card this is intentionally silent — a Backlog
      // column full of cards with no timer widget at all reads as normal,
      // not broken. In the full task detail panel (size="md"), though, the
      // same empty space sits inside its own bordered Card and reads as a
      // blank/broken section rather than an intentional state, so give it a
      // reason there — same "visible reason" principle as the !canEdit
      // branch above.
      if (size !== "md") return null;
      return <span className="text-[11px] italic text-mute">Move to To Do or On Hold to start tracking time</span>;
    }
    const check = canStart(engineState, task.id, currentUserId);
    return (
      <div className="flex flex-col items-start gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size={size}
            variant="primary"
            disabled={!check.ok || isPending}
            onClick={(e) => {
              e.stopPropagation();
              onStart(task.id);
            }}
            className="shadow-none"
          >
            <PlayIcon /> Start
          </Button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              openManualLog();
            }}
            className="text-[11px] font-semibold text-body underline decoration-dotted underline-offset-2 hover:text-ink"
          >
            Log time manually
          </button>
        </div>
        {!check.ok && <span className="text-[11px] leading-tight text-mute">{check.reason}</span>}

        <ConfirmDialog
          open={manualOpen}
          title="Log time manually"
          description={`Record time already worked on "${task.title}" — this marks the task Completed, same as Stop.`}
          confirmLabel="Log entry"
          widthClassName="max-w-md"
          busy={manualSubmitting}
          confirmDisabled={toDurationMinutes(manualDraft) <= 0}
          onConfirm={submitManualLog}
          onCancel={() => setManualOpen(false)}
        >
          <ManualLogFields
            draft={manualDraft}
            onChange={setManualDraft}
            maxDaysBack={manualSettings?.max_days_back ?? null}
            error={manualError}
          />
        </ConfirmDialog>
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
        <Button
          size={size}
          variant="secondary"
          disabled={isPending}
          onClick={(e) => {
            e.stopPropagation();
            onPause(ownEntry);
          }}
        >
          <PauseIcon /> Pause
        </Button>
      ) : (
        (() => {
          const check = canResume(engineState, ownEntry.id, currentUserId);
          return (
            <div className="flex flex-col items-start gap-1">
              <Button
                size={size}
                variant="primary"
                disabled={!check.ok || isPending}
                onClick={(e) => {
                  e.stopPropagation();
                  onResume(ownEntry);
                }}
              >
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
        disabled={isPending}
        onClick={(e) => {
          e.stopPropagation();
          requestStop(ownEntry);
        }}
        title={confirmingStop ? "Click again to confirm — this can't be undone" : "Stop is irreversible"}
        className={confirmingStop ? "animate-pulse" : undefined}
      >
        <StopIcon /> {confirmingStop ? "Confirm Stop?" : "Stop"}
      </Button>
    </div>
  );
}
