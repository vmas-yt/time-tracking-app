"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { User, UserRole } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";

const ROLE_LABEL: Record<UserRole, string> = {
  employee: "Employee",
  manager: "Manager",
  admin: "Admin",
};

/** Create/edit slide-over for a user — replaces the old inline
 * `CreateUserForm` (a form dropped below the table header) and `EditUserRow`
 * (a row swapped out for inputs in place). Same two API calls
 * (`createUser`/`updateUser`), same manager-picker restriction to
 * active manager/admin users (mirrors the backend's own `manager_id`
 * validation), same min-8-character password rule on create — pure
 * presentation change onto the shared `SlideOver` pattern. Password reset is
 * a separate, unrelated action and intentionally isn't part of this panel. */
export function UserFormPanel({
  open,
  mode,
  user,
  users,
  onClose,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "edit";
  user: User | null;
  users: User[];
  onClose: () => void;
  onSaved: (user: User, opts: { created: boolean }) => void;
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<UserRole>("employee");
  const [managerId, setManagerId] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (mode === "edit" && user) {
      setFullName(user.full_name);
      setEmail(user.email);
      setRole(user.role);
      setManagerId(user.manager_id ?? "");
    } else {
      setFullName("");
      setEmail("");
      setRole("employee");
      setManagerId("");
    }
    setPassword("");
    setError(null);
  }, [open, mode, user]);

  if (!open) return null;

  const managerOptions = users.filter(
    (u) => u.id !== user?.id && u.is_active && (u.role === "manager" || u.role === "admin")
  );

  const canSubmit =
    email.trim().length > 0 && fullName.trim().length > 0 && (mode === "edit" || password.length >= 8);

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
          role,
          manager_id: managerId || null,
          password,
        });
        onSaved(created, { created: true });
      } else if (user) {
        const updated = await api.updateUser(user.id, {
          full_name: fullName.trim(),
          email: email.trim(),
          role,
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
          <Select value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
            <option value="employee">Employee</option>
            <option value="manager">Manager</option>
            <option value="admin">Admin</option>
          </Select>
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Manager</span>
          <Select value={managerId} onChange={(e) => setManagerId(e.target.value)}>
            <option value="">— no manager —</option>
            {managerOptions.map((m) => (
              <option key={m.id} value={m.id}>
                {m.full_name} ({ROLE_LABEL[m.role]})
              </option>
            ))}
          </Select>
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
