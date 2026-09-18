"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Project } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";

/** Create/edit slide-over for a project — mirrors `UserFormPanel`'s
 * `mode: "create" | "edit"` shape. Edit now that `PATCH /projects/{id}`
 * exists (name/description, partial update); create still posts name +
 * description exactly as before. */
export function ProjectFormPanel({
  open,
  mode,
  project,
  onClose,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "edit";
  project: Project | null;
  onClose: () => void;
  onSaved: (project: Project, opts: { created: boolean }) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (mode === "edit" && project) {
      setName(project.name);
      setDescription(project.description ?? "");
    } else {
      setName("");
      setDescription("");
    }
    setError(null);
  }, [open, mode, project]);

  if (!open) return null;

  const handleClose = () => {
    onClose();
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "create") {
        const created = await api.createProject(name.trim(), description.trim() || undefined);
        onSaved(created, { created: true });
      } else if (project) {
        const updated = await api.updateProject(project.id, {
          name: name.trim(),
          description: description.trim(),
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
    <SlideOver open={open} onClose={handleClose} widthClassName="max-w-[440px]">
      <SlideOverHeader onClose={handleClose}>
        <div>
          <h2 className="text-lg font-bold tracking-tight text-ink">
            {mode === "create" ? "Add project" : "Edit project"}
          </h2>
          <p className="mt-1 text-xs text-mute">
            {mode === "create"
              ? "Optional grouping for tasks — most work happens directly on the board without a project. Employees pick from this list on the Add/Edit Task panel."
              : `Editing ${project?.name ?? "project"}.`}
          </p>
        </div>
      </SlideOverHeader>
      <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 p-6">
        {error && <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{error}</p>}
        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Name</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="Project name" />
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Description (optional)</span>
          <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description" />
        </label>
        <div className="mt-auto flex gap-2 border-t border-canvas pt-4">
          <Button variant="primary" type="submit" disabled={!name.trim() || submitting} className="flex-1">
            {submitting ? "Saving…" : mode === "create" ? "Create project" : "Save changes"}
          </Button>
          <Button variant="tertiary" type="button" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
        </div>
      </form>
    </SlideOver>
  );
}
