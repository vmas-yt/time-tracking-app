"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { BoardConfig, Task, TaskCategory, TaskPriority, TaskStatus, TaskType, TimeEntry, User } from "@/lib/types";
import { TASK_CATEGORIES } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { SwimLane } from "./SwimLane";

interface KanbanBoardProps {
  projectId?: string;
}

const UNASSIGNED_LANE = "__unassigned__";

function laneKeyFor(task: Task, field: BoardConfig["swimlane_field"]): string {
  switch (field) {
    case "assignee":
      return task.assignee_id ?? UNASSIGNED_LANE;
    case "task_type":
      return task.task_type;
    case "category":
      return task.category;
    case "priority":
      return task.priority;
  }
}

function laneLabelFor(key: string, field: BoardConfig["swimlane_field"], users: User[]): string {
  if (field === "assignee") {
    if (key === UNASSIGNED_LANE) return "Unassigned";
    return users.find((u) => u.id === key)?.full_name ?? "Unassigned";
  }
  if (field === "task_type") return key === "ad_hoc" ? "Ad-hoc" : "Normal";
  if (field === "category") return TASK_CATEGORIES.find((c) => c.key === key)?.label ?? key;
  if (field === "priority") return key === "expedite" ? "Expedite" : "Normal";
  return key;
}

export function KanbanBoard({ projectId }: KanbanBoardProps) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [openEntries, setOpenEntries] = useState<TimeEntry[]>([]);
  const [boardConfig, setBoardConfig] = useState<BoardConfig>({
    swimlane_field: "assignee",
    updated_at: "",
  });
  const [draggingTask, setDraggingTask] = useState<Task | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [newTitle, setNewTitle] = useState("");
  const [newCategory, setNewCategory] = useState<TaskCategory>("meeting");
  const [newType, setNewType] = useState<TaskType>("normal");
  const [newPriority, setNewPriority] = useState<TaskPriority>("normal");

  const load = () => {
    api.listTasks(projectId ? { projectId } : undefined).then(setTasks).catch(console.error);
    api.listUsers().then(setUsers).catch(console.error);
    api.listOpenTimers().then(setOpenEntries).catch(console.error);
    api.getBoardConfig().then(setBoardConfig).catch(console.error);
  };

  useEffect(load, [projectId]);

  const lanes = useMemo(() => {
    const byLane = new Map<string, Task[]>();
    for (const task of tasks) {
      const key = laneKeyFor(task, boardConfig.swimlane_field);
      byLane.set(key, [...(byLane.get(key) ?? []), task]);
    }
    return Array.from(byLane.entries()).map(([key, laneTasks]) => ({
      key,
      label: laneLabelFor(key, boardConfig.swimlane_field, users),
      tasks: laneTasks,
    }));
  }, [tasks, users, boardConfig.swimlane_field]);

  const handleDrop = async (task: Task, status: TaskStatus) => {
    setDraggingTask(null);
    if (task.status === status) return;
    try {
      await api.updateTask(task.id, { status });
      // A manual move to On Hold can auto-pause the task's timer server-side,
      // so refresh open timers too, not just the task list.
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not move task");
    }
  };

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    try {
      const task = await api.createTask({
        title: newTitle.trim(),
        project_id: projectId ?? null,
        category: newCategory,
        task_type: newType,
        priority: newPriority,
      });
      setTasks((prev) => [...prev, task]);
      setNewTitle("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create task");
    }
  };

  return (
    <div className="space-y-8">
      {error && (
        <p
          className="cursor-pointer rounded-xl bg-negative-bg px-4 py-2 text-sm text-canvas"
          onClick={() => setError(null)}
        >
          {error} <span className="opacity-70">(click to dismiss)</span>
        </p>
      )}
      <form onSubmit={handleCreateTask} className="flex flex-wrap gap-2">
        <Input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          placeholder="New task title"
          className="max-w-xs"
        />
        <Select
          value={newCategory}
          onChange={(e) => setNewCategory(e.target.value as TaskCategory)}
          className="w-auto"
        >
          {TASK_CATEGORIES.filter((c) => c.key !== "other").map((c) => (
            <option key={c.key} value={c.key}>
              {c.label}
            </option>
          ))}
        </Select>
        <Select value={newType} onChange={(e) => setNewType(e.target.value as TaskType)} className="w-auto">
          <option value="normal">Normal</option>
          <option value="ad_hoc">Ad-hoc</option>
        </Select>
        <Select
          value={newPriority}
          onChange={(e) => setNewPriority(e.target.value as TaskPriority)}
          className="w-auto"
        >
          <option value="normal">Normal</option>
          <option value="expedite">Expedite</option>
        </Select>
        <Button variant="primary" type="submit">
          + Add task
        </Button>
      </form>
      <div className="space-y-6">
        {lanes.map(({ key, label, tasks: laneTasks }) => (
          <SwimLane
            key={key}
            label={label}
            tasks={laneTasks}
            openEntries={openEntries}
            onTimerChange={load}
            onDrop={handleDrop}
            draggingTask={draggingTask}
            onDragStart={setDraggingTask}
          />
        ))}
      </div>
    </div>
  );
}
