"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { errorMessage } from "@/lib/errors";
import type { Department, Role, Team, User } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TeamFormPanel } from "./TeamFormPanel";

/** Teams list/table — same table + slide-over shape as `ProjectsPage`/
 * `DepartmentsPage`. Deactivating a team is blocked (409) while it still has
 * active members (Users with `team_id` pointing at it), surfaced plainly
 * rather than swallowed, same as the department guard. */
export default function TeamsPage() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [activeTeam, setActiveTeam] = useState<Team | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([
      api.listTeams({ includeInactive: true }),
      api.listDepartments({ includeInactive: true }),
      api.listUsers({ includeInactive: true }),
      // Round B3: manager-picker eligibility needs role_id, not just the
      // legacy `role` enum (§3.2) — see TeamFormPanel.
      api.getRoles(),
    ])
      .then(([teamList, departmentList, userList, roleList]) => {
        setTeams(teamList);
        setDepartments(departmentList);
        setUsers(userList);
        setRoles(roleList);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const upsert = (saved: Team, created: boolean) => {
    setTeams((prev) => (created ? [...prev, saved] : prev.map((t) => (t.id === saved.id ? saved : t))));
  };

  const handleDeactivate = async (id: string) => {
    setBusyId(id);
    try {
      const updated = await api.deactivateTeam(id);
      // Still shows (grayed out) with a Reactivate action.
      upsert(updated, false);
      setError(null);
    } catch (err) {
      // Most likely the 409 "still has active members" guard — surface it
      // plainly rather than silently failing.
      setError(errorMessage(err));
    } finally {
      setConfirmingId(null);
      setBusyId(null);
    }
  };

  const handleReactivate = async (id: string) => {
    setBusyId(id);
    try {
      const updated = await api.updateTeam(id, { is_active: true });
      upsert(updated, false);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const departmentName = (id: string) => departments.find((d) => d.id === id)?.name ?? "—";
  const managerName = (id: string | null) => (id ? users.find((u) => u.id === id)?.full_name ?? "—" : "—");

  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <div>
          <CardTitle>Teams</CardTitle>
          <p className="mt-1 text-xs text-mute">
            Users assigned to a team (Users admin page) have their manager kept in sync with the team&rsquo;s manager.
          </p>
        </div>
        <Button
          size="sm"
          variant="primary"
          disabled={departments.filter((d) => d.is_active).length === 0}
          title={departments.filter((d) => d.is_active).length === 0 ? "Add an active department first." : undefined}
          onClick={() => {
            setFormMode("create");
            setActiveTeam(null);
            setFormOpen(true);
          }}
        >
          + Add team
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

        {loading ? (
          <p className="text-sm text-mute">Loading teams…</p>
        ) : teams.length === 0 ? (
          <p className="text-sm text-mute">No teams yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-mute/20 text-left text-xs uppercase text-mute">
                  <th className="py-2 font-semibold">Name</th>
                  <th className="py-2 font-semibold">Department</th>
                  <th className="py-2 font-semibold">Manager</th>
                  <th className="py-2 font-semibold">Status</th>
                  <th className="py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {teams.map((t) => (
                  <tr key={t.id} className={cn("border-b border-canvas-soft last:border-0", !t.is_active && "opacity-50")}>
                    <td className="py-2 font-medium text-ink">{t.name}</td>
                    <td className="py-2 text-body">{departmentName(t.department_id)}</td>
                    <td className="py-2 text-body">{managerName(t.manager_id)}</td>
                    <td className="py-2">
                      {t.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="red">Inactive</Badge>}
                    </td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-1.5">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setFormMode("edit");
                            setActiveTeam(t);
                            setFormOpen(true);
                          }}
                        >
                          Edit
                        </Button>
                        {t.is_active ? (
                          <Button
                            variant="danger"
                            size="sm"
                            onClick={() => setConfirmingId(t.id)}
                            disabled={busyId === t.id}
                          >
                            Deactivate
                          </Button>
                        ) : (
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={() => handleReactivate(t.id)}
                            disabled={busyId === t.id}
                          >
                            Reactivate
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardBody>

      <TeamFormPanel
        open={formOpen}
        mode={formMode}
        team={activeTeam}
        departments={departments}
        users={users}
        roles={roles}
        onClose={() => setFormOpen(false)}
        onSaved={(saved, opts) => {
          upsert(saved, opts.created);
          setFormOpen(false);
        }}
      />

      <ConfirmDialog
        open={confirmingId !== null}
        title="Deactivate this team?"
        description="Fails instead of deactivating anything if members are still assigned to it — reassign or deactivate those users first. This can be reversed later."
        confirmLabel="Deactivate"
        tone="danger"
        busy={confirmingId !== null && busyId === confirmingId}
        onConfirm={() => confirmingId && handleDeactivate(confirmingId)}
        onCancel={() => setConfirmingId(null)}
      />
    </Card>
  );
}
