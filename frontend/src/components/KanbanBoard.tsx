"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Task, TaskStatus, TimeEntry, User } from "@/lib/types";
import { SwimLane } from "./SwimLane";

interface KanbanBoardProps {
  projectId: string;
}

export function KanbanBoard({ projectId }: KanbanBoardProps) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [activeEntry, setActiveEntry] = useState<TimeEntry | null>(null);
  const [draggingTask, setDraggingTask] = useState<Task | null>(null);

  useEffect(() => {
    api.listTasks(projectId).then(setTasks).catch(console.error);
    api.listUsers().then(setUsers).catch(console.error);
    api.getActiveTimer().then(setActiveEntry).catch(console.error);
  }, [projectId]);

  const [newTaskTitle, setNewTaskTitle] = useState("");

  const lanes = useMemo(() => {
    const byAssignee = new Map<string | null, Task[]>();
    byAssignee.set(null, []);
    for (const task of tasks) {
      const key = task.assignee_id;
      byAssignee.set(key, [...(byAssignee.get(key) ?? []), task]);
    }
    return Array.from(byAssignee.entries()).map(([assigneeId, laneTasks]) => ({
      assignee: users.find((u) => u.id === assigneeId) ?? null,
      tasks: laneTasks,
    }));
  }, [tasks, users]);

  const handleDrop = async (task: Task, status: TaskStatus) => {
    setDraggingTask(null);
    if (task.status === status) return;
    const updated = await api.updateTaskStatus(task.id, status, 0);
    setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
  };

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTaskTitle.trim()) return;
    const task = await api.createTask({ title: newTaskTitle.trim(), project_id: projectId });
    setTasks((prev) => [...prev, task]);
    setNewTaskTitle("");
  };

  return (
    <div className="kanban-board">
      <form onSubmit={handleCreateTask} className="kanban-board__new-task">
        <input
          value={newTaskTitle}
          onChange={(e) => setNewTaskTitle(e.target.value)}
          placeholder="New task title"
        />
        <button className="timer-btn timer-btn--start" type="submit">
          + Add task
        </button>
      </form>
      {lanes.map(({ assignee, tasks: laneTasks }) => (
        <SwimLane
          key={assignee?.id ?? "unassigned"}
          assignee={assignee}
          tasks={laneTasks}
          activeEntry={activeEntry}
          onTimerChange={setActiveEntry}
          onDrop={handleDrop}
          draggingTask={draggingTask}
          onDragStart={setDraggingTask}
        />
      ))}
    </div>
  );
}
