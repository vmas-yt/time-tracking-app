"use client";

import type { Task, TimeEntry } from "@/lib/types";
import { TimerControls } from "./TimerControls";

interface TaskCardProps {
  task: Task;
  activeEntry: TimeEntry | null;
  onTimerChange: (entry: TimeEntry | null) => void;
  onDragStart: (task: Task) => void;
}

export function TaskCard({ task, activeEntry, onTimerChange, onDragStart }: TaskCardProps) {
  return (
    <div
      className="task-card"
      draggable
      onDragStart={() => onDragStart(task)}
    >
      <div className="task-card__title">{task.title}</div>
      {task.description && <div className="task-card__description">{task.description}</div>}
      <TimerControls taskId={task.id} activeEntry={activeEntry} onChange={onTimerChange} />
    </div>
  );
}
