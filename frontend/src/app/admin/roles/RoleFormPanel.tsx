"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Role } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";

/** Create/rename slide-over for a custom role (docs/design/custom-roles-design.md
 * §2.2/§2.3, §5.1). Name only — `key` is server-generated (slugified from the
 * name, de-duplicated with a numeric suffix) and never client-settable; shown
 * read-only in edit mode purely for transparency, mirroring
 * `CustomFieldFormPanel`'s disabled "Type" field convention. Only ever opened
 * for a custom role — built-in rows have their Edit action disabled at the
 * table level (§5.1), since `PATCH /roles/{id}` 409s on `is_builtin`. */
export function RoleFormPanel({
  open,
  mode,
  role,
  onClose,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "edit";
  role: Role | null;
  onClose: () => void;
  onSaved: (role: Role, opts: { created: boolean }) => void;
}) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(mode === "edit" && role ? role.name : "");
    setError(null);
  }, [open, mode, role]);

  if (!open) return null;

  const canSubmit = name.trim().length > 0;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "create") {
        const created = await api.createRole(name.trim());
        onSaved(created, { created: true });
      } else if (role) {
        const updated = await api.updateRole(role.id, name.trim());
        onSaved(updated, { created: false });
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SlideOver open={open} onClose={onClose} widthClassName="max-w-[420px]">
      <SlideOverHeader onClose={onClose}>
        <div>
          <h2 className="text-lg font-bold tracking-tight text-ink">
            {mode === "create" ? "Add role" : "Rename role"}
          </h2>
          <p className="mt-1 text-xs text-mute">
            {mode === "create"
              ? "Creates a custom role with no permissions granted yet — add them afterward from its row."
              : `Editing ${role?.name ?? "role"}.`}
          </p>
        </div>
      </SlideOverHeader>

      <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 p-6">
        {error && <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{error}</p>}

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Name</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Team Lead" />
        </label>

        {mode === "edit" && role && (
          <label className="space-y-1.5 text-sm">
            <span className="font-semibold text-ink">Key</span>
            <Input value={role.key} disabled />
            <p className="text-xs text-mute">
              Generated from the name at creation and permanent — code and permission grants refer to this, not
              the display name.
            </p>
          </label>
        )}

        <div className="mt-auto flex gap-2 border-t border-canvas pt-4">
          <Button variant="primary" type="submit" disabled={!canSubmit || submitting} className="flex-1">
            {submitting ? "Saving…" : mode === "create" ? "Create role" : "Save changes"}
          </Button>
          <Button variant="tertiary" type="button" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
        </div>
      </form>
    </SlideOver>
  );
}
