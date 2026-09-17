"use client";

import type { Task, TaskStatus, TimeEntry } from "@/lib/types";
import { TASK_STATUSES } from "@/lib/types";
import { cn } from "@/lib/cn";
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
    <section>
      <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-mute">{label}</h3>
      <div className="grid grid-cols-5 gap-3">
        {TASK_STATUSES.map(({ key, label: columnLabel }) => {
          const droppable = DROPPABLE_STATUSES.has(key);
          const columnTasks = tasks.filter((t) => t.status === key);
          return (
            <div
              key={key}
              className={cn(
                "min-h-[96px] rounded-xl border border-transparent p-2",
                droppable && draggingTask && "border-dashed border-primary-active bg-primary-pale/40"
              )}
              onDragOver={droppable ? (e) => e.preventDefault() : undefined}
              onDrop={droppable ? () => draggingTask && onDrop(draggingTask, key) : undefined}
            >
              <div className="mb-2 flex items-center justify-between px-1">
                <span className="text-xs font-semibold text-body">
                  {columnLabel}
                  {!droppable && <span className="text-mute"> · timer</span>}
                </span>
                {columnTasks.length > 0 && (
                  <span className="rounded-full bg-canvas px-1.5 text-[10px] font-semibold text-body">
                    {columnTasks.length}
                  </span>
                )}
              </div>
              <div className="space-y-2">
                {columnTasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    openEntries={openEntries}
                    onTimerChange={onTimerChange}
                    onDragStart={onDragStart}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
