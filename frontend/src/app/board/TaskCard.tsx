"use client";

import type { DragEvent } from "react";
import type { Task } from "@/lib/types";
import { TASK_CATEGORIES } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import { useBoard } from "@/board/store";
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
  const categoryLabel =
    TASK_CATEGORIES.find((c) => c.key === task.category)?.label ?? task.category_other_text ?? task.category;
  // Only draggable if the task hasn't reached its terminal status and the
  // viewer is actually allowed to edit it — dragging a task you can only
  // view (e.g. a manager's report) would just 403 on drop.
  const draggable = task.status !== "completed" && board.canEditTask(task);

  return (
    <div
      draggable={draggable}
      onDragStart={draggable ? (e) => onDragStart(e, task) : undefined}
      onDragEnd={onDragEnd}
      className={cn(
        "group space-y-2.5 rounded-xl bg-canvas p-3.5 transition-all duration-150 ease-out",
        draggable ? "cursor-grab active:cursor-grabbing" : "cursor-default",
        isDragging ? "scale-[0.97] opacity-40" : "hover:-translate-y-0.5 hover:bg-primary-pale/30",
        "focus-within:ring-2 focus-within:ring-primary-neutral"
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

      <button
        type="button"
        onClick={() => board.selectTask(task.id)}
        className="block text-left text-sm font-semibold leading-snug text-ink hover:underline"
      >
        {task.title}
      </button>

      {task.description && <p className="line-clamp-2 text-xs leading-relaxed text-mute">{task.description}</p>}

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
