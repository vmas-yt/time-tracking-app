"use client";

import type { DragEvent } from "react";
import type { Task, TaskStatus } from "@/lib/types";
import { TASK_STATUSES } from "@/lib/types";
import { cn } from "@/lib/cn";
import type { Lane } from "@/board/lanes";
import { TaskCard } from "./TaskCard";

interface SwimLaneProps {
  lane: Lane;
  draggingTaskId: string | null;
  validTargets: Set<TaskStatus>;
  hoverColumn: TaskStatus | null;
  onDragStart: (e: DragEvent<HTMLDivElement>, task: Task) => void;
  onDragEnd: () => void;
  onColumnDragOver: (status: TaskStatus) => void;
  onColumnDragLeave: () => void;
  onDrop: (status: TaskStatus) => void;
}

function EmptyColumn() {
  return (
    <div className="flex h-16 items-center justify-center rounded-lg border border-dashed border-mute/25 text-[11px] text-mute/70">
      No tasks
    </div>
  );
}

export function SwimLane({
  lane,
  draggingTaskId,
  validTargets,
  hoverColumn,
  onDragStart,
  onDragEnd,
  onColumnDragOver,
  onColumnDragLeave,
  onDrop,
}: SwimLaneProps) {
  return (
    <section>
      <h3 className="mb-2.5 flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-mute">
        {lane.label}
        <span className="rounded-full bg-canvas-soft px-1.5 py-0.5 text-[10px] font-semibold text-body">
          {lane.tasks.length}
        </span>
      </h3>
      <div className="grid grid-cols-5 gap-3">
        {TASK_STATUSES.map(({ key, label: columnLabel }) => {
          const columnTasks = lane.tasks.filter((t) => t.status === key);
          const isDragActive = draggingTaskId !== null;
          const isValidTarget = isDragActive && validTargets.has(key);
          const isTimerOnly = key === "in_progress" || key === "completed";
          const isHovering = hoverColumn === key;

          return (
            <div
              key={key}
              onDragOver={
                isValidTarget
                  ? (e) => {
                      e.preventDefault();
                      onColumnDragOver(key);
                    }
                  : undefined
              }
              onDragLeave={isValidTarget ? onColumnDragLeave : undefined}
              onDrop={
                isValidTarget
                  ? (e) => {
                      e.preventDefault();
                      onDrop(key);
                    }
                  : undefined
              }
              className={cn(
                "min-h-[110px] rounded-xl p-2 transition-colors duration-150",
                isValidTarget && "ring-2 ring-dashed ring-primary-active bg-primary-pale/30",
                isValidTarget && isHovering && "bg-primary-pale/60 ring-primary",
                isDragActive && !isValidTarget && "opacity-60"
              )}
            >
              <div className="mb-2 flex items-center justify-between px-1">
                <span className="text-xs font-semibold text-body">
                  {columnLabel}
                  {isTimerOnly && <span className="ml-1 text-[10px] font-normal text-mute">· timer only</span>}
                </span>
              </div>
              <div className="space-y-2">
                {columnTasks.length === 0 ? (
                  <EmptyColumn />
                ) : (
                  columnTasks.map((task) => (
                    <TaskCard
                      key={task.id}
                      task={task}
                      isDragging={draggingTaskId === task.id}
                      onDragStart={onDragStart}
                      onDragEnd={onDragEnd}
                    />
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
