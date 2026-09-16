"use client";

import type { Task, TaskStatus, TimeEntry } from "@/lib/types";
import { TASK_STATUSES } from "@/lib/types";
import { TaskCard } from "./TaskCard";

const DROPPABLE_STATUSES = new Set<TaskStatus>(["backlog", "todo", "on_hold"]);

interface SwimLaneProps {
  label: string;
  tasks: Task[];
  openEntries: TimeEntry[];
  onTimerChange: () => void;
  onDrop: (task: Task, status: TaskStatus) => void;
  draggingTask: Task | null;
  onDragStart: (task: Task) => void;
}

export function SwimLane({
  label,
  tasks,
  openEntries,
  onTimerChange,
  onDrop,
  draggingTask,
  onDragStart,
}: SwimLaneProps) {
  return (
    <div className="swimlane">
      <div className="swimlane__header">{label}</div>
      <div className="swimlane__columns">
        {TASK_STATUSES.map(({ key, label: columnLabel }) => {
          const droppable = DROPPABLE_STATUSES.has(key);
          return (
            <div
              key={key}
              className="swimlane__column"
              onDragOver={droppable ? (e) => e.preventDefault() : undefined}
              onDrop={droppable ? () => draggingTask && onDrop(draggingTask, key) : undefined}
            >
              <div className="swimlane__column-label">
                {columnLabel}
                {!droppable && <span className="swimlane__column-hint"> (via timer)</span>}
              </div>
              {tasks
                .filter((t) => t.status === key)
                .map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    openEntries={openEntries}
                    onTimerChange={onTimerChange}
                    onDragStart={onDragStart}
                  />
                ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
