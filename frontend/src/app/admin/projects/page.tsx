"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Project } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ProjectFormPanel } from "./ProjectFormPanel";

/** Projects list/table — was previously an inline create-form + `<ul>` list
 * stacked into the single long admin page. Same two endpoints
 * (`listProjects`/`createProject`/`deleteProject`), same 409 "has tasks
 * linked to it" delete guard surfaced as an error rather than swallowed. */
export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [activeProject, setActiveProject] = useState<Project | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    api
      .listProjects()
      .then((list) => {
        setProjects(list);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleDelete = async (id: string) => {
    setBusyId(id);
    try {
      await api.deleteProject(id);
      setProjects((prev) => prev.filter((p) => p.id !== id));
      setError(null);
    } catch (err) {
      // Most likely the 409 "has tasks linked to it" guard — surface it
      // plainly rather than silently failing.
      setError(errorMessage(err));
    } finally {
      setConfirmingId(null);
      setBusyId(null);
    }
  };

  return (
    <Card>
      <CardHeader className="flex items-center justify-between">
        <div>
          <CardTitle>Projects</CardTitle>
          <p className="mt-1 text-xs text-mute">
            Optional groupings for tasks — most work happens directly on the board without a project.
          </p>
        </div>
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            setFormMode("create");
            setActiveProject(null);
            setFormOpen(true);
          }}
        >
          + Add project
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
          <p className="text-sm text-mute">Loading projects…</p>
        ) : projects.length === 0 ? (
          <p className="text-sm text-mute">No projects yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-mute/20 text-left text-xs uppercase text-mute">
                  <th className="py-2 font-semibold">Name</th>
                  <th className="py-2 font-semibold">Description</th>
                  <th className="py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id} className="border-b border-canvas-soft last:border-0">
                    <td className="py-2 font-medium text-ink">{p.name}</td>
                    <td className="py-2 text-body">{p.description || "—"}</td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-1.5">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setFormMode("edit");
                            setActiveProject(p);
                            setFormOpen(true);
                          }}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => setConfirmingId(p.id)}
                          disabled={busyId === p.id}
                        >
                          Remove
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

      <ProjectFormPanel
        open={formOpen}
        mode={formMode}
        project={activeProject}
        onClose={() => setFormOpen(false)}
        onSaved={(saved, { created }) => {
          setProjects((prev) => (created ? [...prev, saved] : prev.map((p) => (p.id === saved.id ? saved : p))));
          setFormOpen(false);
        }}
      />

      <ConfirmDialog
        open={confirmingId !== null}
        title="Remove this project?"
        description="Fails instead of removing anything if tasks are still linked to it — move or unlink them first."
        confirmLabel="Remove"
        tone="danger"
        busy={confirmingId !== null && busyId === confirmingId}
        onConfirm={() => confirmingId && handleDelete(confirmingId)}
        onCancel={() => setConfirmingId(null)}
      />
    </Card>
  );
}
