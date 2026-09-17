import type { BoardConfig, DropdownOption, Task, User } from "@/lib/types";
import { TASK_CATEGORIES, TASK_PRIORITIES } from "@/lib/types";
import { optionLabel } from "@/lib/options";

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

function laneLabelFor(
  key: string,
  field: BoardConfig["swimlane_field"],
  users: User[],
  categoryOptions: DropdownOption[],
  priorityOptions: DropdownOption[]
): string {
  if (field === "assignee") {
    if (key === UNASSIGNED_LANE) return "Unassigned";
    return users.find((u) => u.id === key)?.full_name ?? "Unassigned";
  }
  if (field === "task_type") return key === "ad_hoc" ? "Ad-hoc" : "Normal";
  // Category/priority are admin-editable dropdowns now (§2 of
  // custom-fields-admin-design.md) — resolve the live label, falling back to
  // the seeded-default label list, then the raw stored value, so a lane
  // never renders blank for a value the live options fetch doesn't know
  // about (e.g. it loaded before an admin-added option existed).
  if (field === "category") {
    return categoryOptions.length
      ? optionLabel(categoryOptions, key)
      : TASK_CATEGORIES.find((c) => c.key === key)?.label ?? key;
  }
  if (field === "priority") {
    return priorityOptions.length
      ? optionLabel(priorityOptions, key)
      : TASK_PRIORITIES.find((p) => p.key === key)?.label ?? key;
  }
  return key;
}

/** Determines lane order for a grouping field: known/seeded values first (in
 * their configured position order), then any other values actually present
 * on a task but not in that known list — appended rather than dropped. This
 * matters now that category/priority are admin-editable: a lane-grouped
 * board must never silently hide tasks whose category/priority was added
 * after this list was last fetched or isn't in the seed set. */
function orderedKeys(
  field: BoardConfig["swimlane_field"],
  presentKeys: string[],
  users: User[],
  categoryOptions: DropdownOption[],
  priorityOptions: DropdownOption[]
): string[] {
  const present = new Set(presentKeys);
  if (field === "task_type") {
    return ["normal", "ad_hoc"].filter((k) => present.has(k));
  }
  if (field === "category") {
    const known = categoryOptions.length
      ? categoryOptions.slice().sort((a, b) => a.position - b.position).map((o) => o.value)
      : TASK_CATEGORIES.map((c) => c.key);
    const ordered = known.filter((k) => present.has(k));
    const extra = presentKeys.filter((k) => !known.includes(k));
    return [...ordered, ...extra];
  }
  if (field === "priority") {
    const known = priorityOptions.length
      ? priorityOptions.slice().sort((a, b) => a.position - b.position).map((o) => o.value)
      : TASK_PRIORITIES.map((p) => p.key);
    const ordered = known.filter((k) => present.has(k));
    const extra = presentKeys.filter((k) => !known.includes(k));
    return [...ordered, ...extra];
  }
  // assignee: ordered by the users list (stable), then unassigned last.
  const userOrder = users.map((u) => u.id).filter((id) => present.has(id));
  const rest = presentKeys.filter((k) => !userOrder.includes(k));
  return [...userOrder, ...rest];
}

export function groupIntoLanes(
  tasks: Task[],
  users: User[],
  field: BoardConfig["swimlane_field"],
  categoryOptions: DropdownOption[] = [],
  priorityOptions: DropdownOption[] = []
): Lane[] {
  const byLane = new Map<string, Task[]>();
  for (const task of tasks) {
    const key = laneKeyFor(task, field);
    byLane.set(key, [...(byLane.get(key) ?? []), task]);
  }

  const keys = orderedKeys(field, Array.from(byLane.keys()), users, categoryOptions, priorityOptions);

  return keys.map((key) => ({
    key,
    label: laneLabelFor(key, field, users, categoryOptions, priorityOptions),
    tasks: byLane.get(key) ?? [],
  }));
}
