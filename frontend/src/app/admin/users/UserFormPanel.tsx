"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Role, Team, User } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";

/** Create/edit slide-over for a user — replaces the old inline
 * `CreateUserForm` (a form dropped below the table header) and `EditUserRow`
 * (a row swapped out for inputs in place). Same two API calls
 * (`createUser`/`updateUser`), same min-8-character password rule on create —
 * pure presentation change onto the shared `SlideOver` pattern. Password
 * reset is a separate, unrelated action and intentionally isn't part of this
 * panel.
 *
 * Round B3 (docs/design/custom-roles-design.md §5.2): the role picker is
 * sourced from `GET /roles` (builtin + custom) rather than a fixed 3-
 * `UserRole` list, keyed by `role.id`, and the form submits `role_id` —
 * never the legacy `role` field — so assigning a custom role works exactly
 * the same way as assigning a builtin one.
 *
 * Manager is "derived, auto-synced" once a team is assigned: the backend
 * silently overwrites `manager_id` with the team's manager whenever
 * `team_id` is non-null, so once a team is picked the Manager field switches
 * to a read-only display of that team's manager instead of implying it's
 * independently editable. */
export function UserFormPanel({
  open,
  mode,
  user,
  users,
  teams,
  roles,
  onClose,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "edit";
  user: User | null;
  users: User[];
  teams: Team[];
  roles: Role[];
  onClose: () => void;
  onSaved: (user: User, opts: { created: boolean }) => void;
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [roleId, setRoleId] = useState("");
  const [managerId, setManagerId] = useState("");
  const [teamId, setTeamId] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const builtinEmployeeRoleId = roles.find((r) => r.is_builtin && r.key === "employee")?.id ?? "";
  const builtinRoles = roles.filter((r) => r.is_builtin);
  const customRoles = roles.filter((r) => !r.is_builtin);

  useEffect(() => {
    if (!open) return;
    if (mode === "edit" && user) {
      setFullName(user.full_name);
      setEmail(user.email);
      setRoleId(user.role_id ?? builtinEmployeeRoleId);
      setManagerId(user.manager_id ?? "");
      setTeamId(user.team_id ?? "");
    } else {
      setFullName("");
      setEmail("");
      setRoleId(builtinEmployeeRoleId);
      setManagerId("");
      setTeamId("");
    }
    setPassword("");
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode, user]);

  if (!open) return null;

  // Manager-eligibility mirrors the backend's own `validate_manager_id`
  // check (`role_key(manager) == "employee"` is the only disqualifier,
  // §3.2 CONFIRMED no change needed for Round B3) — filtering by role_id
  // against the builtin Employee row's id (rather than the legacy `role`
  // enum, which is `null` for any custom-role holder) so a user holding a
  // custom role is correctly still manager-eligible, not silently excluded.
  const managerOptions = users.filter(
    (u) => u.id !== user?.id && u.is_active && u.role_id !== builtinEmployeeRoleId
  );
  const teamOptions = teams.filter((t) => t.is_active);
  const selectedTeam = teams.find((t) => t.id === teamId);
  const teamManager = selectedTeam?.manager_id ? users.find((u) => u.id === selectedTeam.manager_id) : undefined;
  // Whatever we send as `manager_id` is overwritten server-side once a team
  // is set — send the team's manager anyway so the UI stays consistent even
  // if the backend behavior ever changes.
  const effectiveManagerId = teamId ? selectedTeam?.manager_id ?? null : managerId || null;

  const canSubmit =
    email.trim().length > 0 &&
    fullName.trim().length > 0 &&
    roleId.length > 0 &&
    (mode === "edit" || password.length >= 8);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "create") {
        const created = await api.createUser({
          email: email.trim(),
          full_name: fullName.trim(),
          role_id: roleId,
          manager_id: effectiveManagerId,
          team_id: teamId || null,
          password,
        });
        onSaved(created, { created: true });
      } else if (user) {
        const updated = await api.updateUser(user.id, {
          full_name: fullName.trim(),
          email: email.trim(),
          role_id: roleId,
          manager_id: effectiveManagerId,
          team_id: teamId || null,
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
          <h2 className="text-lg font-bold tracking-tight text-ink">
            {mode === "create" ? "Add user" : "Edit user"}
          </h2>
          <p className="mt-1 text-xs text-mute">
            {mode === "create"
              ? "Creates an account with an initial password."
              : `Editing ${user?.full_name ?? "user"}.`}
          </p>
        </div>
      </SlideOverHeader>

      <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 p-6">
        {error && <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{error}</p>}

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Full name</span>
          <Input value={fullName} onChange={(e) => setFullName(e.target.value)} autoFocus />
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Email</span>
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Role</span>
          <Select value={roleId} onChange={(e) => setRoleId(e.target.value)}>
            {roleId === "" && (
              <option value="" disabled>
                Select a role…
              </option>
            )}
            <optgroup label="Built-in">
              {builtinRoles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </optgroup>
            {customRoles.length > 0 && (
              <optgroup label="Custom">
                {customRoles.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </optgroup>
            )}
          </Select>
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Team</span>
          <Select value={teamId} onChange={(e) => setTeamId(e.target.value)}>
            <option value="">— no team —</option>
            {teamOptions.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </Select>
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Manager</span>
          {teamId ? (
            <>
              <p className="w-full rounded-md border border-mute/30 bg-canvas-soft px-4 py-2.5 text-sm text-body">
                {teamManager?.full_name ?? "— no manager —"}
              </p>
              <p className="text-xs text-mute">Set by Team ({selectedTeam?.name}) — change the team&rsquo;s manager instead.</p>
            </>
          ) : (
            <Select value={managerId} onChange={(e) => setManagerId(e.target.value)}>
              <option value="">— no manager —</option>
              {managerOptions.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.full_name} ({m.role_name})
                </option>
              ))}
            </Select>
          )}
        </label>

        {mode === "create" && (
          <label className="space-y-1.5 text-sm">
            <span className="font-semibold text-ink">Initial password</span>
            <Input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Min 8 characters"
            />
            {password.length > 0 && password.length < 8 && (
              <p className="text-xs text-negative">Password must be at least 8 characters.</p>
            )}
          </label>
        )}

        <div className="mt-auto flex gap-2 border-t border-canvas pt-4">
          <Button variant="primary" type="submit" disabled={!canSubmit || submitting} className="flex-1">
            {submitting ? "Saving…" : mode === "create" ? "Create user" : "Save changes"}
          </Button>
          <Button variant="tertiary" type="button" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
        </div>
      </form>
    </SlideOver>
  );
}
