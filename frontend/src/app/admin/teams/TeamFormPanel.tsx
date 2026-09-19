"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Department, Role, Team, User } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";

/** Create/edit slide-over for a team — mirrors `ProjectFormPanel`'s
 * `mode: "create" | "edit"` shape. Manager picker is the same pattern as
 * `UserFormPanel`'s ("— no manager —" option, otherwise every active,
 * manager-eligible user) since a Team's manager is who Users assigned to it
 * get synced to. Department is required (every team hangs off exactly one
 * department).
 *
 * Round B3 (docs/design/custom-roles-design.md §3.2): manager-eligibility
 * mirrors the backend's own `validate_manager_id` check — "not the builtin
 * Employee role" — via `role_id`, not the legacy `role` enum (which is
 * `null` for a custom-role holder), so a user holding a custom role is
 * correctly still offered as a manager candidate. */
export function TeamFormPanel({
  open,
  mode,
  team,
  departments,
  users,
  roles,
  onClose,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "edit";
  team: Team | null;
  departments: Department[];
  users: User[];
  roles: Role[];
  onClose: () => void;
  onSaved: (team: Team, opts: { created: boolean }) => void;
}) {
  const [name, setName] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [managerId, setManagerId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeDepartments = departments.filter((d) => d.is_active);
  const builtinEmployeeRoleId = roles.find((r) => r.is_builtin && r.key === "employee")?.id ?? "";
  const managerOptions = users.filter((u) => u.is_active && u.role_id !== builtinEmployeeRoleId);

  useEffect(() => {
    if (!open) return;
    if (mode === "edit" && team) {
      setName(team.name);
      setDepartmentId(team.department_id);
      setManagerId(team.manager_id ?? "");
    } else {
      setName("");
      setDepartmentId(activeDepartments[0]?.id ?? "");
      setManagerId("");
    }
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode, team]);

  if (!open) return null;

  const canSubmit = name.trim().length > 0 && departmentId.length > 0;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "create") {
        const created = await api.createTeam({
          name: name.trim(),
          department_id: departmentId,
          manager_id: managerId || null,
        });
        onSaved(created, { created: true });
      } else if (team) {
        const updated = await api.updateTeam(team.id, {
          name: name.trim(),
          department_id: departmentId,
          manager_id: managerId || null,
        });
        onSaved(updated, { created: false });
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SlideOver open={open} onClose={onClose} widthClassName="max-w-[440px]">
      <SlideOverHeader onClose={onClose}>
        <div>
          <h2 className="text-lg font-bold tracking-tight text-ink">{mode === "create" ? "Add team" : "Edit team"}</h2>
          <p className="mt-1 text-xs text-mute">
            {mode === "create"
              ? "Users assigned to this team have their manager kept in sync with the team's manager."
              : `Editing ${team?.name ?? "team"}.`}
          </p>
        </div>
      </SlideOverHeader>
      <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 p-6">
        {error && <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{error}</p>}

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Name</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="Team name" />
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Department</span>
          <Select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
            <option value="" disabled>
              Select a department…
            </option>
            {activeDepartments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Manager</span>
          <Select value={managerId} onChange={(e) => setManagerId(e.target.value)}>
            <option value="">— no manager —</option>
            {managerOptions.map((m) => (
              <option key={m.id} value={m.id}>
                {m.full_name} ({m.role_name})
              </option>
            ))}
          </Select>
        </label>

        <div className="mt-auto flex gap-2 border-t border-canvas pt-4">
          <Button variant="primary" type="submit" disabled={!canSubmit || submitting} className="flex-1">
            {submitting ? "Saving…" : mode === "create" ? "Create team" : "Save changes"}
          </Button>
          <Button variant="tertiary" type="button" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
        </div>
      </form>
    </SlideOver>
  );
}
