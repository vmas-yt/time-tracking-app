"use client";

import Link from "next/link";
import type { Task, TimeEntry } from "@/lib/types";
import { TASK_CATEGORIES } from "@/lib/types";
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
    <div className="task-card" draggable onDragStart={() => onDragStart(task)}>
      <div className="task-card__badges">
        {task.task_type === "ad_hoc" && <span className="badge badge--ad-hoc">Ad-hoc</span>}
        {task.priority === "expedite" && <span className="badge badge--expedite">Expedite</span>}
        <span className="badge badge--category">{categoryLabel}</span>
      </div>
      <Link href={`/tasks/${task.id}`} className="task-card__title">
        {task.title}
      </Link>
      {task.description && <div className="task-card__description">{task.description}</div>}
      <TimerControls task={task} openEntries={openEntries} onChange={onTimerChange} />
    </div>
  );
}
