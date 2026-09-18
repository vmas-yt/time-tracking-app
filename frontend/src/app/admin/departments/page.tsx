"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { errorMessage } from "@/lib/errors";
import type { Department } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DepartmentFormPanel } from "./DepartmentFormPanel";

/** Departments list/table — top-level org structure that Teams (and, through
 * a Team, Users/Tasks) hang off of. Same table + slide-over shape as
 * `ProjectsPage`; Status/Deactivate/Reactivate follow `DropdownOptionsTable`'s
 * pattern instead since departments carry an `is_active` flag rather than
 * being hard-removable outright — deactivating one is blocked (409) while it
 * still has active teams under it, surfaced plainly rather than swallowed. */
export default function DepartmentsPage() {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [activeDepartment, setActiveDepartment] = useState<Department | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api
      .listDepartments({ includeInactive: true })
      .then((list) => {
        setDepartments(list);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const upsert = (saved: Department, created: boolean) => {
    setDepartments((prev) => (created ? [...prev, saved] : prev.map((d) => (d.id === saved.id ? saved : d))));
  };

  const handleDeactivate = async (id: string) => {
    setBusyId(id);
    try {
      const updated = await api.deactivateDepartment(id);
      // Still shows (grayed out) with a Reactivate action, matching the
      // Users/DropdownOptions tables' lifecycle.
      upsert(updated, false);
      setError(null);
    } catch (err) {
      // Most likely the 409 "still has active teams under it" guard —
      // surface it plainly rather than silently failing.
      setError(errorMessage(err));
    } finally {
      setConfirmingId(null);
      setBusyId(null);
    }
  };

  const handleReactivate = async (id: string) => {
    setBusyId(id);
    try {
      const updated = await api.updateDepartment(id, { is_active: true });
      upsert(updated, false);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <div>
          <CardTitle>Departments</CardTitle>
          <p className="mt-1 text-xs text-mute">
            Top-level org grouping — teams (and their managers) are created underneath a department.
          </p>
        </div>
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            setFormMode("create");
            setActiveDepartment(null);
            setFormOpen(true);
          }}
        >
          + Add department
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
          <p className="text-sm text-mute">Loading departments…</p>
        ) : departments.length === 0 ? (
          <p className="text-sm text-mute">No departments yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-mute/20 text-left text-xs uppercase text-mute">
                  <th className="py-2 font-semibold">Name</th>
                  <th className="py-2 font-semibold">Status</th>
                  <th className="py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {departments.map((d) => (
                  <tr key={d.id} className={cn("border-b border-canvas-soft last:border-0", !d.is_active && "opacity-50")}>
                    <td className="py-2 font-medium text-ink">{d.name}</td>
                    <td className="py-2">
                      {d.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="red">Inactive</Badge>}
                    </td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-1.5">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setFormMode("edit");
                            setActiveDepartment(d);
                            setFormOpen(true);
                          }}
                        >
                          Edit
                        </Button>
                        {d.is_active ? (
                          <Button
                            variant="danger"
                            size="sm"
                            onClick={() => setConfirmingId(d.id)}
                            disabled={busyId === d.id}
                          >
                            Deactivate
                          </Button>
                        ) : (
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={() => handleReactivate(d.id)}
                            disabled={busyId === d.id}
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

      <DepartmentFormPanel
        open={formOpen}
        mode={formMode}
        department={activeDepartment}
        onClose={() => setFormOpen(false)}
        onSaved={(saved, opts) => {
          upsert(saved, opts.created);
          setFormOpen(false);
        }}
      />

      <ConfirmDialog
        open={confirmingId !== null}
        title="Deactivate this department?"
        description="Fails instead of deactivating anything if teams under it are still active — deactivate or move those teams first. This can be reversed later."
        confirmLabel="Deactivate"
        tone="danger"
        busy={confirmingId !== null && busyId === confirmingId}
        onConfirm={() => confirmingId && handleDeactivate(confirmingId)}
        onCancel={() => setConfirmingId(null)}
      />
    </Card>
  );
}
