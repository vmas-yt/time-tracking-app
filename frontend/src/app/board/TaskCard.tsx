"use client";

import type { DragEvent } from "react";
import type { Task } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import { useBoard } from "@/board/store";
import { categoryLabelFor, optionLabel } from "@/lib/options";
import { TimerControls } from "./TimerControls";

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
  // Only draggable if the task hasn't reached its terminal status and the
  // viewer is actually allowed to edit it — dragging a task you can only
  // view (e.g. a manager's report) would just 403 on drop.
  const draggable = task.status !== "completed" && board.canEditTask(task);

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
        isDragging ? "scale-[0.97] opacity-40" : "hover:-translate-y-0.5 hover:bg-primary-pale/30",
        "focus-within:ring-2 focus-within:ring-primary-neutral focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-neutral"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap gap-1">
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

      <div className="pt-0.5">
        <TimerControls
          task={task}
          entries={board.entries}
          currentUserId={board.currentUserId}
          canEdit={board.canEditTask(task)}
          isPending={board.isPending(task.id)}
          onStart={board.start}
          onPause={board.pause}
          onResume={board.resume}
          onStop={board.stop}
        />
      </div>
    </div>
  );
}
