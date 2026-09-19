"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import type { DragEvent } from "react";
import { api } from "@/lib/api";
import type { SwimlaneField, Task, TaskStatus } from "@/lib/types";
import { SWIMLANE_FIELDS } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Select } from "@/components/ui/Input";
import { validDropTargets } from "@/board/engine";
import { groupIntoLanes } from "@/board/lanes";
import { useBoard } from "@/board/store";
import { AddTaskPanel } from "./AddTaskPanel";
import { SwimLane } from "./SwimLane";
import { TaskDetailPanel } from "./TaskDetailPanel";
import { Toast } from "./Toast";

export function BoardScreen() {
  const board = useBoard();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [draggingTaskId, setDraggingTaskId] = useState<string | null>(null);
  const [hoverColumn, setHoverColumn] = useState<TaskStatus | null>(null);
  const [showNewTask, setShowNewTask] = useState(false);
  const [projectName, setProjectName] = useState<string | null>(null);

  // Round C (docs/design/team-scoped-boards-design.md §6.1) — the real,
  // org-chart-`Team`-entity switcher. Mirrors the `?project=<id>` pattern:
  // there's no existing `<Select>`-driven project switcher on this screen to
  // literally mirror (the project filter is link-driven, from elsewhere), so
  // this pushes the `?team=` param via the router directly, preserving any
  // other query params (e.g. `?project=`) already present.
  const handleTeamChange = (id: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (id) params.set("team", id);
    else params.delete("team");
    const qs = params.toString();
    router.push(qs ? `/board?${qs}` : "/board");
  };

  const selectedTeam = board.teams.find((t) => t.id === board.teamId) ?? null;
  const boardTitle = selectedTeam ? (board.effectiveBoardName ?? selectedTeam.name) : "Kanban board";

  useEffect(() => {
    if (!board.projectId) {
      setProjectName(null);
      return;
    }
    let cancelled = false;
    api
      .getProject(board.projectId)
      .then((p) => {
        if (!cancelled) setProjectName(p.name);
      })
      .catch(() => {
        if (!cancelled) setProjectName(null);
      });
    return () => {
      cancelled = true;
    };
  }, [board.projectId]);

  const engineState = { tasks: board.tasks, entries: board.entries };

  const validTargets = useMemo(
    () => (draggingTaskId ? validDropTargets(engineState, draggingTaskId) : new Set<TaskStatus>()),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [draggingTaskId, board.tasks, board.entries]
  );

  const lanes = useMemo(
    () =>
      groupIntoLanes(
        board.tasks,
        board.users,
        board.boardConfig.swimlane_field,
        board.categoryOptions,
        board.priorityOptions
      ),
    [board.tasks, board.users, board.boardConfig.swimlane_field, board.categoryOptions, board.priorityOptions]
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

  if (board.loading) {
    return <p className="text-sm text-mute">Loading board…</p>;
  }

  if (board.error) {
    return (
      <Card className="space-y-3 px-6 py-8 text-center">
        <p className="text-sm text-negative">{board.error}</p>
        <Button variant="secondary" onClick={board.refresh}>
          Try again
        </Button>
      </Card>
    );
  }

  return (
    <div className="space-y-7">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="mt-1 text-3xl font-black tracking-tight text-ink">{boardTitle}</h1>
          <p className="mt-1.5 max-w-xl text-sm text-body">
            Viewing as <span className="font-semibold text-ink">{board.currentUser?.full_name}</span>. Drag cards
            between Backlog, To Do and On Hold; In Progress and Completed only change via the timer.
          </p>
          {board.projectId && (
            <p className="mt-1 text-xs text-mute">
              Filtered to project <span className="font-semibold text-body">{projectName ?? board.projectId}</span> —{" "}
              <Link href="/board" className="underline hover:text-body">
                clear filter
              </Link>
            </p>
          )}
          {selectedTeam && (
            <p className="mt-1 text-xs text-mute">
              {selectedTeam.name}&rsquo;s team board
              {board.effectiveBoardName && board.effectiveBoardName !== selectedTeam.name ? " (renamed)" : ""} —{" "}
              <button type="button" onClick={() => handleTeamChange("")} className="underline hover:text-body">
                view all teams
              </button>
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex items-center gap-2.5 text-sm text-body">
            <span className="font-semibold text-ink">Team</span>
            <Select value={board.teamId ?? ""} onChange={(e) => handleTeamChange(e.target.value)} className="w-auto">
              <option value="">All teams</option>
              {board.teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </Select>
          </label>
          {board.currentUser?.role === "admin" && (
            <label className="flex items-center gap-2.5 text-sm text-body">
              <span className="font-semibold text-ink">Manager</span>
              <Select
                value={board.managerFilter ?? ""}
                onChange={(e) => board.setManagerFilter(e.target.value || null)}
                className="w-auto"
              >
                <option value="">Everyone</option>
                {board.managers.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.full_name}&rsquo;s team
                  </option>
                ))}
              </Select>
            </label>
          )}
          <label
            className="flex items-center gap-2.5 text-sm text-body"
            title={
              board.canManageBoardConfig
                ? undefined
                : "You don't have permission to change swim-lane grouping (see Admin settings)"
            }
          >
            <span className="font-semibold text-ink">Group lanes by</span>
            <Select
              value={board.boardConfig.swimlane_field}
              onChange={(e) => board.setSwimlaneField(e.target.value as SwimlaneField)}
              disabled={!board.canManageBoardConfig}
              className="w-auto"
            >
              {SWIMLANE_FIELDS.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </Select>
          </label>
          <Button
            variant="primary"
            onClick={() => {
              board.selectTask(null); // avoid stacking with an open task-detail panel
              setShowNewTask(true);
            }}
          >
            + Add task
          </Button>
        </div>
      </header>

      <AddTaskPanel open={showNewTask} onClose={() => setShowNewTask(false)} />

      {lanes.length === 0 ? (
        <Card className="px-6 py-12 text-center text-sm text-mute">
          No tasks yet — create one to get started.
        </Card>
      ) : (
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
      )}

      <TaskDetailPanel />
      <Toast toast={board.toast} dismissToast={board.dismissToast} />
    </div>
  );
}
