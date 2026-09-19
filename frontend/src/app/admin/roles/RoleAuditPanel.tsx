"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Role, RolePermissionAuditEntry } from "@/lib/types";
import { PERMISSION_CATALOG } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";
import { formatRelativeTime } from "@/board/format";

function permissionLabel(key: string): string {
  return PERMISSION_CATALOG[key as keyof typeof PERMISSION_CATALOG]?.label ?? key;
}

/** Read-only permission-change history for a custom role (docs/design/
 * custom-roles-design.md §2.7/§5.1) — a plain newest-first list, one entry
 * per `PUT /roles/{id}/permissions` call (already batched server-side), not
 * a timeline visualization. This is an accountability/audit view, not a
 * primary workflow.
 *
 * Only ever opened for a custom role — built-in roles can never hold
 * `RolePermission` rows and so always have empty history (§2.4); the table
 * hides this action entirely for built-ins rather than showing an
 * always-empty panel. */
export function RoleAuditPanel({ open, role, onClose }: { open: boolean; role: Role | null; onClose: () => void }) {
  const [entries, setEntries] = useState<RolePermissionAuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !role) return;
    setEntries(null);
    setError(null);
    api
      .getRoleAudit(role.id)
      .then(setEntries)
      .catch((err) => setError(errorMessage(err)));
  }, [open, role]);

  if (!open || !role) return null;

  return (
    <SlideOver open={open} onClose={onClose} widthClassName="max-w-[480px]">
      <SlideOverHeader onClose={onClose}>
        <div>
          <h2 className="text-lg font-bold tracking-tight text-ink">Permission history — {role.name}</h2>
          <p className="mt-1 text-xs text-mute">Every saved change to this role&rsquo;s permissions, newest first.</p>
        </div>
      </SlideOverHeader>

      <div className="flex-1 space-y-3 p-6">
        {error && <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{error}</p>}

        {!error && entries === null && <p className="text-sm text-mute">Loading history…</p>}

        {entries !== null && entries.length === 0 && (
          <p className="text-sm text-mute">No permission changes have been made to this role yet.</p>
        )}

        {entries !== null && entries.length > 0 && (
          <ul className="space-y-3">
            {entries.map((entry) => (
              <li key={entry.batch_id} className="rounded-xl bg-canvas p-4 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-semibold text-ink">{entry.actor.full_name || entry.actor.email}</span>
                  <span className="text-xs text-mute">{formatRelativeTime(entry.occurred_at)}</span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {entry.added.map((key) => (
                    <Badge key={`added-${key}`} tone="green">
                      +{permissionLabel(key)}
                    </Badge>
                  ))}
                  {entry.removed.map((key) => (
                    <Badge key={`removed-${key}`} tone="red">
                      −{permissionLabel(key)}
                    </Badge>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </SlideOver>
  );
}
