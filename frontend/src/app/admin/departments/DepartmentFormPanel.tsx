"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Department } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";

/** Create/edit slide-over for a department — mirrors `ProjectFormPanel`'s
 * `mode: "create" | "edit"` shape exactly. Status (`is_active`) isn't edited
 * here; it's toggled from the table row's Deactivate/Reactivate action, same
 * split as `DropdownOptionFormPanel` (rename here, activity toggle there). */
export function DepartmentFormPanel({
  open,
  mode,
  department,
  onClose,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "edit";
  department: Department | null;
  onClose: () => void;
  onSaved: (department: Department, opts: { created: boolean }) => void;
}) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(mode === "edit" && department ? department.name : "");
    setError(null);
  }, [open, mode, department]);

  if (!open) return null;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "create") {
        const created = await api.createDepartment(name.trim());
        onSaved(created, { created: true });
      } else if (department) {
        const updated = await api.updateDepartment(department.id, { name: name.trim() });
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
            {mode === "create" ? "Add department" : "Edit department"}
          </h2>
          <p className="mt-1 text-xs text-mute">
            {mode === "create"
              ? "Top-level org grouping — teams (and their managers) are created underneath a department."
              : `Editing ${department?.name ?? "department"}.`}
          </p>
        </div>
      </SlideOverHeader>
      <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 p-6">
        {error && <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{error}</p>}
        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Name</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="Department name" />
        </label>
        <div className="mt-auto flex gap-2 border-t border-canvas pt-4">
          <Button variant="primary" type="submit" disabled={!name.trim() || submitting} className="flex-1">
            {submitting ? "Saving…" : mode === "create" ? "Create department" : "Save changes"}
          </Button>
          <Button variant="tertiary" type="button" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
        </div>
      </form>
    </SlideOver>
  );
}
