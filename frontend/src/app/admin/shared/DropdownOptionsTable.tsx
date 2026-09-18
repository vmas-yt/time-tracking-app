"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { DropdownOption, DropdownOptionScope } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { cn } from "@/lib/cn";
import { DropdownOptionFormPanel } from "./DropdownOptionFormPanel";

/** Table + slide-over form for one `DropdownOption` scope — the shared admin
 * editor reused by the Categories page, the Priorities page, and a
 * select-type custom field's "Options" section. Replaces
 * `DropdownOptionsEditor`'s inline add-row/inline-rename `<ul>` with a table
 * (per the "each sub-section gets its own list screen" restructuring) plus
 * the `DropdownOptionFormPanel` slide-over for add/rename. Built-in-option
 * protection is unchanged: built-ins render their Deactivate control
 * disabled with an explanatory tooltip instead of firing a request the
 * backend is guaranteed to 409 on, and the backend's distinct "Others"
 * message (category_other_text depends on it existing) still surfaces
 * verbatim through `errorMessage`. */
export function DropdownOptionsTable({
  scope,
  customFieldId,
  emptyLabel = "No options yet.",
  panelLayer = 0,
}: {
  scope: DropdownOptionScope;
  customFieldId?: string;
  emptyLabel?: string;
  panelLayer?: 0 | 1;
}) {
  const [options, setOptions] = useState<DropdownOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingOption, setEditingOption] = useState<DropdownOption | null>(null);

  const load = () => {
    setLoading(true);
    api
      .listDropdownOptions({ scope, customFieldId, includeInactive: true })
      .then((list) => {
        setOptions(list.slice().sort((a, b) => a.position - b.position));
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [scope, customFieldId]);

  const handleDeactivate = async (id: string) => {
    setBusyId(id);
    try {
      const updated = await api.deactivateDropdownOption(id);
      setOptions((prev) => prev.map((o) => (o.id === id ? updated : o)));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setConfirmingId(null);
      setBusyId(null);
    }
  };

  const handleReactivate = async (id: string) => {
    setBusyId(id);
    try {
      const updated = await api.updateDropdownOption(id, { is_active: true });
      setOptions((prev) => prev.map((o) => (o.id === id ? updated : o)));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-3">
      {error && (
        <p className="cursor-pointer rounded-lg bg-negative-bg px-3 py-1.5 text-xs text-canvas" onClick={() => setError(null)}>
          {error}
        </p>
      )}

      <div className="flex justify-end">
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            setEditingOption(null);
            setFormOpen(true);
          }}
        >
          + Add option
        </Button>
      </div>

      {loading ? (
        <p className="text-xs text-mute">Loading options…</p>
      ) : options.length === 0 ? (
        <p className="text-xs text-mute">{emptyLabel}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-mute/20 text-left text-xs uppercase text-mute">
                <th className="py-2 font-semibold">Label</th>
                <th className="py-2 font-semibold">Value</th>
                <th className="py-2 font-semibold">Status</th>
                <th className="py-2 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {options.map((o) => (
                <tr key={o.id} className={cn("border-b border-canvas-soft last:border-0", !o.is_active && "opacity-50")}>
                  <td className="py-2 font-medium text-ink">{o.label}</td>
                  <td className="py-2 font-mono text-xs text-mute">{o.value}</td>
                  <td className="py-2">
                    <div className="flex flex-wrap gap-1">
                      {o.is_builtin && <Badge tone="gray">built-in</Badge>}
                      {o.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="red">Inactive</Badge>}
                    </div>
                  </td>
                  <td className="py-2">
                    <div className="flex flex-wrap gap-1.5">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setEditingOption(o);
                          setFormOpen(true);
                        }}
                      >
                        Rename
                      </Button>
                      {o.is_active ? (
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => setConfirmingId(o.id)}
                          disabled={o.is_builtin || busyId === o.id}
                          title={o.is_builtin ? "Built-in options are required and can't be deactivated" : undefined}
                        >
                          Deactivate
                        </Button>
                      ) : (
                        <Button size="sm" variant="primary" onClick={() => handleReactivate(o.id)} disabled={busyId === o.id}>
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

      <DropdownOptionFormPanel
        open={formOpen}
        scope={scope}
        customFieldId={customFieldId}
        option={editingOption}
        layer={panelLayer}
        onClose={() => setFormOpen(false)}
        onSaved={(option, { created }) => {
          setOptions((prev) =>
            created ? [...prev, option] : prev.map((o) => (o.id === option.id ? option : o))
          );
          setFormOpen(false);
        }}
      />

      <ConfirmDialog
        open={confirmingId !== null}
        title="Deactivate this option?"
        description="Tasks that already used it keep showing it; it just disappears from the picker for new selections. This can be reversed later."
        confirmLabel="Deactivate"
        tone="danger"
        busy={confirmingId !== null && busyId === confirmingId}
        onConfirm={() => confirmingId && handleDeactivate(confirmingId)}
        onCancel={() => setConfirmingId(null)}
      />
    </div>
  );
}
