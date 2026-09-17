import type { BoardConfig, Task, User } from "@/lib/types";
import { TASK_CATEGORIES } from "@/lib/types";

export const UNASSIGNED_LANE = "__unassigned__";

export interface Lane {
  key: string;
  label: string;
  tasks: Task[];
}

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

// Fixed, deterministic lane ordering per grouping field so the board doesn't
// reshuffle lanes as tasks move between statuses.
const LANE_ORDER: Record<BoardConfig["swimlane_field"], string[] | null> = {
  assignee: null, // ordered by first-seen / users list instead
  task_type: ["normal", "ad_hoc"],
  category: TASK_CATEGORIES.map((c) => c.key),
  priority: ["normal", "expedite"],
};

export function groupIntoLanes(tasks: Task[], users: User[], field: BoardConfig["swimlane_field"]): Lane[] {
  const byLane = new Map<string, Task[]>();
  for (const task of tasks) {
    const key = laneKeyFor(task, field);
    byLane.set(key, [...(byLane.get(key) ?? []), task]);
  }

  const order = LANE_ORDER[field];
  const keys = order ? order.filter((k) => byLane.has(k)) : Array.from(byLane.keys());

  if (field === "assignee") {
    // Order lanes by the users list (stable), then unassigned last.
    const userOrder = users.map((u) => u.id).filter((id) => byLane.has(id));
    const rest = Array.from(byLane.keys()).filter((k) => !userOrder.includes(k));
    return [...userOrder, ...rest].map((key) => ({
      key,
      label: laneLabelFor(key, field, users),
      tasks: byLane.get(key) ?? [],
    }));
  }

  return keys.map((key) => ({ key, label: laneLabelFor(key, field, users), tasks: byLane.get(key) ?? [] }));
}
