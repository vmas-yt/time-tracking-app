"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Role, User } from "@/lib/types";
import { PERMISSION_CATALOG } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { RoleAuditPanel } from "./RoleAuditPanel";
import { RoleFormPanel } from "./RoleFormPanel";
import { RolePermissionsPanel } from "./RolePermissionsPanel";

// Only one of these is ever open at a time — a single discriminated-union
// state rather than three independent booleans, so opening one action never
// leaves a stale panel from another action mounted underneath it.
type ActivePanel =
  | { type: "form"; mode: "create" | "edit"; role: Role | null }
  | { type: "permissions"; role: Role }
  | { type: "audit"; role: Role };

function permissionsSummary(role: Role): string {
  if (role.key === "admin") return "All permissions (implicit)";
  if (role.is_builtin) return "Fixed — not configurable";
  if (role.permission_keys.length === 0) return "No permissions granted";
  return role.permission_keys
    .map((key) => PERMISSION_CATALOG[key as keyof typeof PERMISSION_CATALOG]?.label ?? key)
    .join(", ");
}

/** Roles admin screen (docs/design/custom-roles-design.md §5.1) — Round B3
 * custom roles + granular permissions. Same table + slide-over shape as
 * `DepartmentsPage`/`TeamsPage`, with built-in rows following
 * `DropdownOptionsTable`'s established "disabled action + explanatory
 * tooltip, never hidden" convention for immutable rows, since
 * `PATCH`/`PUT permissions`/`DELETE /roles/{id}` all 409 on `is_builtin`
 * exactly the way built-in dropdown options 409 on deactivate. */
export default function RolesPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [panel, setPanel] = useState<ActivePanel | null>(null);
  const [confirmingRole, setConfirmingRole] = useState<Role | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    // `users` is fetched purely for the client-side occupancy pre-check
    // before showing the delete confirmation (§5.1) — the server is still
    // the authority (409s regardless), this is UX politeness only.
    Promise.all([api.getRoles(), api.listUsers({ includeInactive: true })])
      .then(([roleList, userList]) => {
        setRoles(roleList);
        setUsers(userList);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const upsertRole = (saved: Role, created: boolean) => {
    setRoles((prev) => (created ? [...prev, saved] : prev.map((r) => (r.id === saved.id ? saved : r))));
  };

  const occupantCount = (roleId: string) => users.filter((u) => u.role_id === roleId).length;

  const handleDelete = async (role: Role) => {
    setBusyId(role.id);
    try {
      await api.deleteRole(role.id);
      setRoles((prev) => prev.filter((r) => r.id !== role.id));
      setError(null);
      setConfirmingRole(null);
    } catch (err) {
      // Most likely the 409 "still occupied" or "has permission-change
      // history" guard — surface it plainly rather than silently failing
      // (the client-side pre-check below is a warning, not a hard block).
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <div>
          <CardTitle>Roles</CardTitle>
          <p className="mt-1 text-xs text-mute">
            Built-in roles (Employee, Manager, Admin) are fixed. Create a custom role to grant a specific set of
            permissions to a group of users.
          </p>
        </div>
        <Button size="sm" variant="primary" onClick={() => setPanel({ type: "form", mode: "create", role: null })}>
          + Add role
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
          <p className="text-sm text-mute">Loading roles…</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-mute/20 text-left text-xs uppercase text-mute">
                  <th className="py-2 font-semibold">Name</th>
                  <th className="py-2 font-semibold">Key</th>
                  <th className="py-2 font-semibold">Type</th>
                  <th className="py-2 font-semibold">Permissions</th>
                  <th className="py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {roles.map((r) => (
                  <tr key={r.id} className="border-b border-canvas-soft last:border-0 align-top">
                    <td className="py-2.5 font-medium text-ink">{r.name}</td>
                    <td className="py-2.5 font-mono text-xs text-mute">{r.key}</td>
                    <td className="py-2.5">
                      {r.is_builtin ? <Badge tone="gray">Built-in</Badge> : <Badge tone="brand">Custom</Badge>}
                    </td>
                    <td className="py-2.5 max-w-xs text-body">{permissionsSummary(r)}</td>
                    <td className="py-2.5">
                      <div className="flex flex-wrap gap-1.5">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={r.is_builtin}
                          title={r.is_builtin ? "Built-in role names are fixed and can't be renamed" : undefined}
                          onClick={() => setPanel({ type: "form", mode: "edit", role: r })}
                        >
                          Edit
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={r.is_builtin}
                          title={
                            r.is_builtin
                              ? r.key === "admin"
                                ? "Admin implicitly has every permission — nothing to configure"
                                : "Built-in roles have fixed, non-configurable permissions"
                              : undefined
                          }
                          onClick={() => setPanel({ type: "permissions", role: r })}
                        >
                          Permissions
                        </Button>
                        {!r.is_builtin && (
                          <Button size="sm" variant="secondary" onClick={() => setPanel({ type: "audit", role: r })}>
                            History
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="danger"
                          disabled={r.is_builtin || busyId === r.id}
                          title={r.is_builtin ? "Built-in roles can't be deleted" : undefined}
                          onClick={() => setConfirmingRole(r)}
                        >
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardBody>

      <RoleFormPanel
        open={panel !== null && panel.type === "form"}
        mode={panel !== null && panel.type === "form" ? panel.mode : "create"}
        role={panel !== null && panel.type === "form" ? panel.role : null}
        onClose={() => setPanel(null)}
        onSaved={(saved, opts) => {
          upsertRole(saved, opts.created);
          setPanel(null);
        }}
      />

      <RolePermissionsPanel
        open={panel !== null && panel.type === "permissions"}
        role={panel !== null && panel.type === "permissions" ? panel.role : null}
        onClose={() => setPanel(null)}
        onSaved={(saved) => {
          upsertRole(saved, false);
          setPanel(null);
        }}
      />

      <RoleAuditPanel
        open={panel !== null && panel.type === "audit"}
        role={panel !== null && panel.type === "audit" ? panel.role : null}
        onClose={() => setPanel(null)}
      />

      <ConfirmDialog
        open={confirmingRole !== null}
        title={`Delete "${confirmingRole?.name ?? ""}"?`}
        description={
          confirmingRole
            ? occupantCount(confirmingRole.id) > 0
              ? `${occupantCount(confirmingRole.id)} user(s) currently hold this role — the server will refuse to delete it until they're reassigned to a different role. This can't be undone.`
              : "This can't be undone. If this role's permissions have ever been changed and saved, deletion is blocked to preserve that audit trail — it can still be renamed or emptied of permissions instead."
            : undefined
        }
        confirmLabel="Delete"
        tone="danger"
        busy={confirmingRole !== null && busyId === confirmingRole.id}
        onConfirm={() => confirmingRole && handleDelete(confirmingRole)}
        onCancel={() => setConfirmingRole(null)}
      />
    </Card>
  );
}
