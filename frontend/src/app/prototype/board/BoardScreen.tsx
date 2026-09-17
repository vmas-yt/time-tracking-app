"use client";

import { useMemo, useState } from "react";
import type { DragEvent } from "react";
import type { SwimlaneField, Task, TaskStatus } from "@/lib/types";
import { SWIMLANE_FIELDS } from "@/lib/types";
import { Select } from "@/components/ui/Input";
import { validDropTargets } from "@/prototype/board/engine";
import { groupIntoLanes } from "@/prototype/board/lanes";
import { usePrototypeBoard } from "@/prototype/board/store";
import { SwimLane } from "./SwimLane";
import { TaskDetailPanel } from "./TaskDetailPanel";
import { Toast } from "./Toast";

export function BoardScreen() {
  const board = usePrototypeBoard();
  const [draggingTaskId, setDraggingTaskId] = useState<string | null>(null);
  const [hoverColumn, setHoverColumn] = useState<TaskStatus | null>(null);

  const engineState = { tasks: board.tasks, entries: board.entries, audit: board.audit, comments: board.comments };

  const validTargets = useMemo(
    () => (draggingTaskId ? validDropTargets(engineState, draggingTaskId) : new Set<TaskStatus>()),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [draggingTaskId, board.tasks, board.entries]
  );

  const lanes = useMemo(
    () => groupIntoLanes(board.tasks, board.users, board.boardConfig.swimlane_field),
    [board.tasks, board.users, board.boardConfig.swimlane_field]
  );

  const handleDragStart = (e: DragEvent<HTMLDivElement>, task: Task) => {
    setDraggingTaskId(task.id);
    e.dataTransfer.effectAllowed = "move";
  };

  const handleDragEnd = () => {
    setDraggingTaskId(null);
    setHoverColumn(null);
  };

  const handleDrop = (status: TaskStatus) => {
    if (draggingTaskId) board.move(draggingTaskId, status);
    setDraggingTaskId(null);
    setHoverColumn(null);
  };

  const currentUser = board.users.find((u) => u.id === board.currentUserId);

  return (
    <div className="space-y-7">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-mute">Design-approval prototype</p>
          <h1 className="mt-1 text-3xl font-black tracking-tight text-ink">Kanban board</h1>
          <p className="mt-1.5 max-w-xl text-sm text-body">
            Viewing as <span className="font-semibold text-ink">{currentUser?.full_name}</span> — dummy data, fully
            interactive. Drag cards between Backlog, To Do and On Hold; In Progress and Completed only change via the
            timer.
          </p>
        </div>
        <label className="flex items-center gap-2.5 text-sm text-body">
          <span className="font-semibold text-ink">Group lanes by</span>
          <Select
            value={board.boardConfig.swimlane_field}
            onChange={(e) => board.setSwimlaneField(e.target.value as SwimlaneField)}
            className="w-auto"
          >
            {SWIMLANE_FIELDS.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </Select>
        </label>
      </header>

      <div className="space-y-8">
        {lanes.map((lane) => (
          <SwimLane
            key={lane.key}
            lane={lane}
            draggingTaskId={draggingTaskId}
            validTargets={validTargets}
            hoverColumn={hoverColumn}
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
            onColumnDragOver={setHoverColumn}
            onColumnDragLeave={() => setHoverColumn(null)}
            onDrop={handleDrop}
          />
        ))}
      </div>

      <TaskDetailPanel />
      <Toast />
    </div>
  );
}
