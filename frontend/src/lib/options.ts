import type { DropdownOption, Task, User } from "./types";
import { TASK_CATEGORIES, TASK_PRIORITIES } from "./types";

/** Active options only — what a picker should offer for new selections
 * (docs/design/custom-fields-admin-design.md §1.4/§2.6). */
export function activeOptions(options: DropdownOption[] | null | undefined): DropdownOption[] {
  return (options ?? []).filter((o) => o.is_active);
}

/** Resolve a stored value (category/priority/select-custom-field) to its
 * display label. Looks at the *full* options list (active + inactive) so a
 * value set before its option was deactivated still shows a real label
 * instead of a raw slug; falls back to the raw value itself if no matching
 * option exists at all (deleted field, or a value the viewer's role can't
 * see inactive options for — see §2.6/§1.4). */
export function optionLabel(options: DropdownOption[] | null | undefined, value: string): string {
  const match = (options ?? []).find((o) => o.value === value);
  return match?.label ?? value;
}

/** Builds the <select> option list for editing a `select`-type custom field
 * or category/priority: active options in position order, plus — if the
 * task's current value isn't among them (deactivated after being set) — a
 * disabled trailing entry so the field doesn't render blank (§1.4). */
export function selectOptionsFor(
  options: DropdownOption[] | null | undefined,
  currentValue: string | null | undefined
): { value: string; label: string; disabled: boolean }[] {
  const all = options ?? [];
  const active = all.filter((o) => o.is_active).map((o) => ({ value: o.value, label: o.label, disabled: false }));
  if (currentValue && !active.some((o) => o.value === currentValue)) {
    const stale = all.find((o) => o.value === currentValue);
    active.push({ value: currentValue, label: stale ? `${stale.label} (inactive)` : currentValue, disabled: true });
  }
  return active;
}

/** Builds a `<select>` option list for a user picker (manager/assignee):
 * active, eligible users in list order, plus — if the current value isn't
 * among them (the previously-picked user has since been deactivated, or no
 * longer passes `eligible`) — a disabled trailing entry so the field doesn't
 * render blank or silently drop the selection (same pattern as
 * `selectOptionsFor` above, User-flavored). Requires the FULL user list
 * (active + inactive) so a stale current value can still be resolved to its
 * real name — pass an already-active-only list and the stale entry degrades
 * to showing the raw id instead of a name. `labelFor` defaults to just the
 * name (assignee pickers); manager pickers pass one that also shows the
 * role, e.g. `(u) => \`${u.full_name} (${u.role_name})\`` — same
 * disambiguation the pre-existing manager `<option>`s already showed. */
export function userOptionsFor(
  users: User[],
  currentId: string | null | undefined,
  eligible: (u: User) => boolean = () => true,
  labelFor: (u: User) => string = (u) => u.full_name
): { value: string; label: string; disabled: boolean }[] {
  const active = users
    .filter((u) => u.is_active && eligible(u))
    .map((u) => ({ value: u.id, label: labelFor(u), disabled: false }));
  if (currentId && !active.some((o) => o.value === currentId)) {
    const stale = users.find((u) => u.id === currentId);
    active.push({
      value: currentId,
      label: stale ? `${stale.full_name} (Deactivated)` : currentId,
      disabled: true,
    });
  }
  return active;
}

/** Category label for display, in priority order: the task's own free-text
 * description (only set — and only meaningful — when `category === "other"`),
 * then the live `DropdownOption` label, then the seeded-default label, then
 * the raw stored value. Shared by `TaskCard`, `TaskDetailPanel`, and the
 * standalone task page so all three resolve a category the same way. */
export function categoryLabelFor(
  task: Pick<Task, "category" | "category_other_text">,
  categoryOptions: DropdownOption[]
): string {
  if (task.category === "other" && task.category_other_text) return task.category_other_text;
  const live = categoryOptions.find((o) => o.value === task.category)?.label;
  if (live) return live;
  return TASK_CATEGORIES.find((c) => c.key === task.category)?.label ?? task.category;
}

/** Priority label — same fallback chain as `categoryLabelFor` minus the
 * category_other_text special case. */
export function priorityLabelFor(value: string, priorityOptions: DropdownOption[]): string {
  const live = priorityOptions.find((o) => o.value === value)?.label;
  if (live) return live;
  return TASK_PRIORITIES.find((p) => p.key === value)?.label ?? value;
}
