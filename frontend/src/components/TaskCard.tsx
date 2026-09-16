"use client";

import Link from "next/link";
import type { Task, TimeEntry } from "@/lib/types";
import { TASK_CATEGORIES } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { TimerControls } from "./TimerControls";

interface TaskCardProps {
  task: Task;
  openEntries: TimeEntry[];
  onTimerChange: () => void;
  onDragStart: (task: Task) => void;
}

export function TaskCard({ task, openEntries, onTimerChange, onDragStart }: TaskCardProps) {
  const categoryLabel =
    TASK_CATEGORIES.find((c) => c.key === task.category)?.label ??
    task.category_other_text ??
    task.category;

  return (
    <div
      className="cursor-grab space-y-2 rounded-lg border border-gray-200 bg-white p-3 shadow-sm transition-shadow hover:shadow-md active:cursor-grabbing"
      draggable
      onDragStart={() => onDragStart(task)}
    >
      <div className="flex flex-wrap gap-1">
        {task.task_type === "ad_hoc" && <Badge tone="amber">Ad-hoc</Badge>}
        {task.priority === "expedite" && <Badge tone="red">Expedite</Badge>}
        <Badge tone="blue">{categoryLabel}</Badge>
      </div>
      <Link
        href={`/tasks/${task.id}`}
        className="block text-sm font-medium text-gray-900 hover:text-brand-600"
      >
        {task.title}
      </Link>
      {task.description && (
        <p className="line-clamp-2 text-xs text-gray-500">{task.description}</p>
      )}
      <TimerControls task={task} openEntries={openEntries} onChange={onTimerChange} />
    </div>
  );
}
