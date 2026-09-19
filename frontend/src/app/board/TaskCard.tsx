"use client";

import type { DragEvent } from "react";
import type { Task } from "@/lib/types";
import { Badge, ManualEntryBadge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import { useBoard } from "@/board/store";
import { formatRelativeTime } from "@/board/format";
import { categoryLabelFor, optionLabel } from "@/lib/options";
import { TimerControls } from "./TimerControls";

function CalendarIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="5" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="2" />
      <path d="M3 10h18M8 3v4M16 3v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

interface TaskCardProps {
  task: Task;
  isDragging: boolean;
  onDragStart: (e: DragEvent<HTMLDivElement>, task: Task) => void;
  onDragEnd: () => void;
}

function initials(name: string): string {
  return name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function TaskCard({ task, isDragging, onDragStart, onDragEnd }: TaskCardProps) {
  const board = useBoard();
  const assignee = board.users.find((u) => u.id === task.assignee_id);
  const categoryLabel = categoryLabelFor(task, board.categoryOptions);
  // Whether the current viewer may edit/drag/drive this task's timer at all
  // (assignee/creator/admin). `false` covers every "I can see this card but
  // it isn't mine" case — a manager reviewing a report's task (existing) and,
  // as of Round C (docs/design/team-scoped-boards-design.md §5.1/§9), a
  // teammate who can now see this card purely because it shares their
  // `team_id`. Both get the identical read-only treatment below rather than
  // a team-specific special case, since the underlying rule ("can't edit
  // what isn't yours") is the same regardless of *why* you can view it.
  const editable = board.canEditTask(task);
  // Only draggable if the task hasn't reached its terminal status and the
  // viewer is actually allowed to edit it — dragging a task you can only
  // view (e.g. a manager's report, or a teammate's card) would just 403 on
  // drop.
  const draggable = task.status !== "completed" && editable;

  // Compact custom-field badges (docs/design/custom-fields-admin-design.md
  // §1.4): at most 2 fields with a non-empty value, in definition order,
  // omitted entirely if none are set — no empty-state clutter on the card.
  const customBadges = board.customFields
    .map((field) => {
      const raw = task.custom_values[field.id];
      if (!raw) return null;
      const display =
        field.field_type === "select"
          ? optionLabel(field.options, raw)
          : field.field_type === "boolean"
            ? raw === "true"
              ? "Yes"
              : "No"
            : raw;
      return { key: field.id, label: `${field.name}: ${display}` };
    })
    .filter((b): b is { key: string; label: string } => b !== null)
    .slice(0, 2);

  return (
    <div
      role="button"
      tabIndex={0}
      draggable={draggable}
      onClick={() => board.selectTask(task.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          board.selectTask(task.id);
        }
      }}
      onDragStart={draggable ? (e) => onDragStart(e, task) : undefined}
      onDragEnd={onDragEnd}
      className={cn(
        "group space-y-2.5 rounded-xl bg-canvas p-3.5 transition-all duration-150 ease-out",
        // The whole card opens task detail (Jira-style), so it's always a
        // pointer target; draggable cards additionally show a grabbing
        // cursor once a drag gesture actually starts (mouse held + moved) —
        // the two affordances aren't mutually exclusive.
        "cursor-pointer",
        draggable && "active:cursor-grabbing",
        isDragging
          ? "scale-[0.97] opacity-40"
          : editable
            ? "hover:-translate-y-0.5 hover:bg-primary-pale/30"
            : // Read-only card (§9): deliberately no lift-on-hover — that
              // motion reads as "this is draggable/actionable," which would
              // be actively misleading here. A plain background tint still
              // signals the card responds to hover (it opens read-only
              // detail) without implying drag-and-drop.
              "hover:bg-canvas-soft",
        "focus-within:ring-2 focus-within:ring-primary-neutral focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-neutral"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          {!editable && (
            <Badge
              tone="gray"
              title="You can view this task but can't edit it, drag it, or control its timer"
            >
              View only
            </Badge>
          )}
          {task.is_manual_entry && <ManualEntryBadge />}
          {task.task_type === "ad_hoc" && <Badge tone="amber">Ad-hoc</Badge>}
          {task.priority === "expedite" && <Badge tone="red">Expedite</Badge>}
          <Badge tone="blue">{categoryLabel}</Badge>
        </div>
        {assignee && (
          <span
            title={assignee.full_name}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-[10px] font-bold text-primary"
          >
            {initials(assignee.full_name)}
          </span>
        )}
      </div>

      <p className="text-sm font-semibold leading-snug text-ink">{task.title}</p>

      {task.description && <p className="line-clamp-2 text-xs leading-relaxed text-mute">{task.description}</p>}

      {customBadges.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {customBadges.map((b) => (
            <Badge key={b.key} tone="gray">
              {b.label}
            </Badge>
          ))}
        </div>
      )}

      <div
        className="flex items-center gap-1 text-[11px] text-mute"
        title="Reference date for this card — creation, start, or completion, whichever is most relevant right now"
      >
        <CalendarIcon />
        {formatRelativeTime(task.card_date)}
      </div>

      <div className="pt-0.5">
        <TimerControls
          task={task}
          entries={board.entries}
          currentUserId={board.currentUserId}
          canEdit={editable}
          isPending={board.isPending(task.id)}
          onStart={board.start}
          onPause={board.pause}
          onResume={board.resume}
          onStop={board.stop}
          onManualLog={async (taskId, input) => {
            const result = await board.logManualTime(taskId, input);
            return result !== null;
          }}
        />
      </div>
    </div>
  );
}
