"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { PermissionGroup, PermissionKey, Role } from "@/lib/types";
import { PERMISSION_CATALOG, PERMISSION_KEYS } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";

// Display order for the three §5.1 checklist groupings — matches the
// catalog's own Organization / Board & task admin / Visibility ordering.
const GROUPS: PermissionGroup[] = ["Organization", "Board & task admin", "Visibility"];

/** Permissions checklist slide-over for a custom role (docs/design/
 * custom-roles-design.md §2.4/§5.1) — all 12 `PERMISSION_KEYS`, grouped into
 * the three catalog sections. Save sends the *full* checked set to
 * `PUT /roles/{id}/permissions` (full-replacement semantics, not incremental
 * add/remove) — unchecking everything and saving is a valid way to empty a
 * role's grants.
 *
 * Only ever opened for a custom role — built-in rows have this action
 * disabled at the table level, since `PUT /roles/{id}/permissions` 409s on
 * `is_builtin` (their capabilities are fixed/implicit, §2.4). */
export function RolePermissionsPanel({
  open,
  role,
  onClose,
  onSaved,
}: {
  open: boolean;
  role: Role | null;
  onClose: () => void;
  onSaved: (role: Role) => void;
}) {
  const [checked, setChecked] = useState<Set<PermissionKey>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !role) return;
    setChecked(new Set(role.permission_keys as PermissionKey[]));
    setError(null);
  }, [open, role]);

  if (!open || !role) return null;

  const toggle = (key: PermissionKey) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const handleSave = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const updated = await api.updateRolePermissions(role.id, Array.from(checked));
      onSaved(updated);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SlideOver open={open} onClose={onClose} widthClassName="max-w-[480px]">
      <SlideOverHeader onClose={onClose}>
        <div>
          <h2 className="text-lg font-bold tracking-tight text-ink">Permissions — {role.name}</h2>
          <p className="mt-1 text-xs text-mute">
            Saving replaces this role&rsquo;s entire permission set with exactly what&rsquo;s checked below.
          </p>
        </div>
      </SlideOverHeader>

      <div className="flex flex-1 flex-col gap-5 p-6">
        {error && <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{error}</p>}

        {GROUPS.map((group) => {
          const keysInGroup = PERMISSION_KEYS.filter((key) => PERMISSION_CATALOG[key].group === group);
          return (
            <div key={group} className="space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wide text-mute">{group}</h3>
              <div className="space-y-2 rounded-xl bg-canvas p-4">
                {keysInGroup.map((key) => (
                  <label key={key} className="flex items-start gap-2.5 text-sm">
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 shrink-0 rounded border-ink text-primary focus:ring-primary-neutral"
                      checked={checked.has(key)}
                      onChange={() => toggle(key)}
                    />
                    <span className="text-ink">{PERMISSION_CATALOG[key].label}</span>
                  </label>
                ))}
              </div>
              {group === "Visibility" && (
                <p className="text-xs text-mute">
                  Visibility permissions let a role see more — they never grant editing or deleting. Seeing all
                  tasks or controlling anyone&rsquo;s timer still doesn&rsquo;t allow editing or deleting a task;
                  that stays limited to its assignee, its creator, or an Admin.
                </p>
              )}
            </div>
          );
        })}

        <div className="mt-auto flex gap-2 border-t border-canvas pt-4">
          <Button variant="primary" onClick={handleSave} disabled={submitting} className="flex-1">
            {submitting ? "Saving…" : "Save permissions"}
          </Button>
          <Button variant="tertiary" type="button" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
        </div>
      </div>
    </SlideOver>
  );
}
