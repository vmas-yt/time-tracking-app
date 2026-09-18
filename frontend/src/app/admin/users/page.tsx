"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { errorMessage } from "@/lib/errors";
import type { Team, User, UserRole } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { UserFormPanel } from "./UserFormPanel";
import { UserProfilePanel } from "./UserProfilePanel";

const ROLE_LABEL: Record<UserRole, string> = {
  employee: "Employee",
  manager: "Manager",
  admin: "Admin",
};

/** Inline password-reset row — the one remaining inline-edit affordance in
 * this table. Not part of the create/edit-goes-to-a-slide-over restructuring
 * (it isn't creating or editing the user entity itself), so it's left as-is. */
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
      <td className="py-2 text-sm text-body" colSpan={5}>
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

/** Users list — kept as a table per the restructuring brief ("the list/table
 * itself should stay a table"); only create and edit moved off inline forms
 * and onto the shared `SlideOver` pattern via `UserFormPanel`. */
export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [resettingId, setResettingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [profileUserId, setProfileUserId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([api.listUsers({ includeInactive: true }), api.listTeams({ includeInactive: true })])
      .then(([userList, teamList]) => {
        setUsers(userList);
        setTeams(teamList);
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
    setUsers((prev) =>
      prev.some((u) => u.id === updated.id) ? prev.map((u) => (u.id === updated.id ? updated : u)) : [...prev, updated]
    );
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

  if (!currentUser) return null;

  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <div>
          <CardTitle>Users</CardTitle>
          <p className="mt-1 text-xs text-mute">
            Create accounts, assign roles/managers, and deactivate access. Click a name for their profile.
          </p>
        </div>
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            setFormMode("create");
            setEditingUser(null);
            setFormOpen(true);
          }}
        >
          + Add user
        </Button>
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
                  <th className="py-2 font-semibold">Team</th>
                  <th className="py-2 font-semibold">Manager</th>
                  <th className="py-2 font-semibold">Status</th>
                  <th className="py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
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
                  const team = teams.find((t) => t.id === u.team_id);
                  return (
                    <tr key={u.id} className={cn("border-b border-canvas-soft last:border-0", !u.is_active && "opacity-50")}>
                      <td className="py-2 font-medium text-ink">
                        <button type="button" onClick={() => setProfileUserId(u.id)} className="hover:underline">
                          {u.full_name}
                        </button>
                      </td>
                      <td className="py-2 text-mute">{u.email}</td>
                      <td className="py-2 text-body">{ROLE_LABEL[u.role]}</td>
                      <td className="py-2 text-body">{team?.name ?? "—"}</td>
                      <td className="py-2 text-body">{manager?.full_name ?? "—"}</td>
                      <td className="py-2">
                        {u.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="red">Deactivated</Badge>}
                      </td>
                      <td className="py-2">
                        <div className="flex flex-wrap gap-1.5">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => {
                              setFormMode("edit");
                              setEditingUser(u);
                              setFormOpen(true);
                            }}
                          >
                            Edit
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => setResettingId(u.id)}>
                            Reset password
                          </Button>
                          <Button
                            size="sm"
                            variant={u.is_active ? "danger" : "primary"}
                            onClick={() => handleToggleActive(u)}
                            disabled={busyId === u.id || (u.is_active && u.id === currentUser.id)}
                            title={
                              u.is_active && u.id === currentUser.id
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

      <UserFormPanel
        open={formOpen}
        mode={formMode}
        user={editingUser}
        users={users}
        teams={teams}
        onClose={() => setFormOpen(false)}
        onSaved={(user, { created }) => {
          upsertUser(user);
          setFormOpen(false);
          flash(created ? `${user.full_name} created.` : `${user.full_name} updated.`);
        }}
      />

      {profileUserId && (
        <UserProfilePanel
          user={users.find((u) => u.id === profileUserId)!}
          users={users}
          onClose={() => setProfileUserId(null)}
        />
      )}
    </Card>
  );
}
