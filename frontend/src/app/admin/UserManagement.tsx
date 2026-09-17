"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { User, UserRole } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Input";

const ROLE_LABEL: Record<UserRole, string> = {
  employee: "Employee",
  manager: "Manager",
  admin: "Admin",
};

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong";
}

/** New-user creation form. Manager picker only offers users whose role is
 * manager/admin — mirrors the backend's own `manager_id` validation
 * (docs/design/auth-rbac-design.md §7.2/§7.3) so the picker never submits a
 * request the API is guaranteed to reject. */
function CreateUserForm({
  users,
  onCreated,
  onCancel,
  onError,
}: {
  users: User[];
  onCreated: (user: User) => void;
  onCancel: () => void;
  onError: (message: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<UserRole>("employee");
  const [managerId, setManagerId] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const managerOptions = users.filter((u) => u.is_active && (u.role === "manager" || u.role === "admin"));

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !fullName.trim() || password.length < 8) return;
    setSubmitting(true);
    try {
      const created = await api.createUser({
        email: email.trim(),
        full_name: fullName.trim(),
        role,
        manager_id: managerId || null,
        password,
      });
      onCreated(created);
      setEmail("");
      setFullName("");
      setRole("employee");
      setManagerId("");
      setPassword("");
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-2 rounded-xl bg-canvas-soft p-4 sm:grid-cols-2">
      <Input
        placeholder="Full name"
        value={fullName}
        onChange={(e) => setFullName(e.target.value)}
        autoFocus
      />
      <Input
        placeholder="Email"
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <Select value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
        <option value="employee">Employee</option>
        <option value="manager">Manager</option>
        <option value="admin">Admin</option>
      </Select>
      <Select value={managerId} onChange={(e) => setManagerId(e.target.value)}>
        <option value="">— no manager —</option>
        {managerOptions.map((m) => (
          <option key={m.id} value={m.id}>
            {m.full_name} ({ROLE_LABEL[m.role]})
          </option>
        ))}
      </Select>
      <Input
        placeholder="Initial password (min 8 characters)"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        className="sm:col-span-2"
      />
      <div className="flex gap-2 sm:col-span-2">
        <Button
          variant="primary"
          type="submit"
          disabled={!email.trim() || !fullName.trim() || password.length < 8 || submitting}
        >
          {submitting ? "Creating…" : "Create user"}
        </Button>
        <Button variant="tertiary" type="button" onClick={onCancel}>
          Cancel
        </Button>
      </div>
      {password.length > 0 && password.length < 8 && (
        <p className="text-xs text-negative sm:col-span-2">Password must be at least 8 characters.</p>
      )}
    </form>
  );
}

/** Inline row-edit form for name/email/role/manager — chosen over a modal
 * since the admin table already exposes role/manager as always-visible
 * selects; extending the same row rather than popping a dialog keeps every
 * user-editing affordance in one place. */
function EditUserRow({
  user,
  users,
  onSaved,
  onCancel,
  onError,
}: {
  user: User;
  users: User[];
  onSaved: (user: User) => void;
  onCancel: () => void;
  onError: (message: string) => void;
}) {
  const [fullName, setFullName] = useState(user.full_name);
  const [email, setEmail] = useState(user.email);
  const [role, setRole] = useState<UserRole>(user.role);
  const [managerId, setManagerId] = useState(user.manager_id ?? "");
  const [submitting, setSubmitting] = useState(false);

  const managerOptions = users.filter(
    (u) => u.id !== user.id && u.is_active && (u.role === "manager" || u.role === "admin")
  );

  const handleSave = async () => {
    setSubmitting(true);
    try {
      const updated = await api.updateUser(user.id, {
        full_name: fullName.trim(),
        email: email.trim(),
        role,
        manager_id: managerId || null,
      });
      onSaved(updated);
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <tr className="border-b border-canvas-soft bg-primary-pale/40 last:border-0">
      <td className="py-2 pr-2">
        <Input value={fullName} onChange={(e) => setFullName(e.target.value)} className="py-1" />
      </td>
      <td className="py-2 pr-2">
        <Input value={email} onChange={(e) => setEmail(e.target.value)} className="py-1" />
      </td>
      <td className="py-2 pr-2">
        <Select value={role} onChange={(e) => setRole(e.target.value as UserRole)} className="w-auto py-1">
          <option value="employee">Employee</option>
          <option value="manager">Manager</option>
          <option value="admin">Admin</option>
        </Select>
      </td>
      <td className="py-2 pr-2">
        <Select value={managerId} onChange={(e) => setManagerId(e.target.value)} className="w-auto py-1">
          <option value="">— none —</option>
          {managerOptions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.full_name}
            </option>
          ))}
        </Select>
      </td>
      <td className="py-2" />
      <td className="py-2">
        <div className="flex gap-1.5">
          <Button size="sm" variant="primary" onClick={handleSave} disabled={submitting}>
            Save
          </Button>
          <Button size="sm" variant="tertiary" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
        </div>
      </td>
    </tr>
  );
}

function ResetPasswordRow({
  user,
  onDone,
  onCancel,
  onError,
}: {
  user: User;
  onDone: () => void;
  onCancel: () => void;
  onError: (message: string) => void;
}) {
  const [newPassword, setNewPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleReset = async () => {
    if (newPassword.length < 8) return;
    setSubmitting(true);
    try {
      await api.resetPassword(user.id, newPassword);
      onDone();
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <tr className="border-b border-canvas-soft bg-canvas-soft last:border-0">
      <td className="py-2 text-sm text-body" colSpan={4}>
        New password for <span className="font-semibold text-ink">{user.full_name}</span>
      </td>
      <td className="py-2" colSpan={2}>
        <div className="flex gap-1.5">
          <Input
            placeholder="New password (min 8 characters)"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="py-1"
          />
          <Button size="sm" variant="primary" onClick={handleReset} disabled={newPassword.length < 8 || submitting}>
            Set
          </Button>
          <Button size="sm" variant="tertiary" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
        </div>
      </td>
    </tr>
  );
}

export function UserManagement({ currentUserId }: { currentUserId: string }) {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [resettingId, setResettingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api
      .listUsers({ includeInactive: true })
      .then((list) => {
        setUsers(list);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const flash = (message: string) => {
    setNotice(message);
    setTimeout(() => setNotice(null), 4000);
  };

  const upsertUser = (updated: User) => {
    setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)));
  };

  const handleToggleActive = async (user: User) => {
    setBusyId(user.id);
    setError(null);
    try {
      const updated = user.is_active
        ? await api.deactivateUser(user.id)
        : await api.updateUser(user.id, { is_active: true });
      upsertUser(updated);
      flash(user.is_active ? `${user.full_name} deactivated.` : `${user.full_name} reactivated.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <CardTitle>Users</CardTitle>
        {!showCreate && (
          <Button size="sm" variant="primary" onClick={() => setShowCreate(true)}>
            + Add user
          </Button>
        )}
      </CardHeader>
      <CardBody className="space-y-4">
        {error && (
          <p
            className="cursor-pointer rounded-xl bg-negative-bg px-4 py-2 text-sm text-canvas"
            onClick={() => setError(null)}
          >
            {error} <span className="opacity-70">(click to dismiss)</span>
          </p>
        )}
        {notice && <p className="rounded-xl bg-primary-pale px-4 py-2 text-sm text-ink-deep">{notice}</p>}

        {showCreate && (
          <CreateUserForm
            users={users}
            onCancel={() => setShowCreate(false)}
            onError={setError}
            onCreated={(user) => {
              setUsers((prev) => [...prev, user]);
              setShowCreate(false);
              flash(`${user.full_name} created.`);
            }}
          />
        )}

        {loading ? (
          <p className="text-sm text-mute">Loading users…</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-mute/20 text-left text-xs uppercase text-mute">
                  <th className="py-2 font-semibold">Name</th>
                  <th className="py-2 font-semibold">Email</th>
                  <th className="py-2 font-semibold">Role</th>
                  <th className="py-2 font-semibold">Manager</th>
                  <th className="py-2 font-semibold">Status</th>
                  <th className="py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  if (editingId === u.id) {
                    return (
                      <EditUserRow
                        key={u.id}
                        user={u}
                        users={users}
                        onCancel={() => setEditingId(null)}
                        onError={setError}
                        onSaved={(updated) => {
                          upsertUser(updated);
                          setEditingId(null);
                          flash(`${updated.full_name} updated.`);
                        }}
                      />
                    );
                  }
                  if (resettingId === u.id) {
                    return (
                      <ResetPasswordRow
                        key={u.id}
                        user={u}
                        onCancel={() => setResettingId(null)}
                        onError={setError}
                        onDone={() => {
                          setResettingId(null);
                          flash(`Password reset for ${u.full_name}.`);
                        }}
                      />
                    );
                  }
                  const manager = users.find((m) => m.id === u.manager_id);
                  return (
                    <tr
                      key={u.id}
                      className={cn(
                        "border-b border-canvas-soft last:border-0",
                        !u.is_active && "opacity-50"
                      )}
                    >
                      <td className="py-2 font-medium text-ink">{u.full_name}</td>
                      <td className="py-2 text-mute">{u.email}</td>
                      <td className="py-2 text-body">{ROLE_LABEL[u.role]}</td>
                      <td className="py-2 text-body">{manager?.full_name ?? "—"}</td>
                      <td className="py-2">
                        {u.is_active ? (
                          <Badge tone="green">Active</Badge>
                        ) : (
                          <Badge tone="red">Deactivated</Badge>
                        )}
                      </td>
                      <td className="py-2">
                        <div className="flex flex-wrap gap-1.5">
                          <Button size="sm" variant="secondary" onClick={() => setEditingId(u.id)}>
                            Edit
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => setResettingId(u.id)}>
                            Reset password
                          </Button>
                          <Button
                            size="sm"
                            variant={u.is_active ? "danger" : "primary"}
                            onClick={() => handleToggleActive(u)}
                            disabled={busyId === u.id || (u.is_active && u.id === currentUserId)}
                            title={
                              u.is_active && u.id === currentUserId
                                ? "You can't deactivate your own account from here."
                                : undefined
                            }
                          >
                            {u.is_active ? "Deactivate" : "Reactivate"}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
