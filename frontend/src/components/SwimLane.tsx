"use client";

import type { Task, TaskStatus, TimeEntry, User } from "@/lib/types";
import { TASK_STATUSES } from "@/lib/types";
import { TaskCard } from "./TaskCard";

interface SwimLaneProps {
  assignee: User | null;
  tasks: Task[];
  activeEntry: TimeEntry | null;
  onTimerChange: (entry: TimeEntry | null) => void;
  onDrop: (task: Task, status: TaskStatus) => void;
  draggingTask: Task | null;
  onDragStart: (task: Task) => void;
}

export function SwimLane({
  assignee,
  tasks,
  activeEntry,
  onTimerChange,
  onDrop,
  draggingTask,
  onDragStart,
}: SwimLaneProps) {
  return (
    <div className="swimlane">
      <div className="swimlane__header">{assignee ? assignee.full_name : "Unassigned"}</div>
      <div className="swimlane__columns">
        {TASK_STATUSES.map(({ key, label }) => (
          <div
            key={key}
            className="swimlane__column"
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => draggingTask && onDrop(draggingTask, key)}
          >
            <div className="swimlane__column-label">{label}</div>
            {tasks
              .filter((t) => t.status === key)
              .map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  activeEntry={activeEntry}
                  onTimerChange={onTimerChange}
                  onDragStart={onDragStart}
                />
              ))}
          </div>
        ))}
      </div>
    </div>
  );
}
