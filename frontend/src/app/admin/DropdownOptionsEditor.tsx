"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import type { DropdownOption, DropdownOptionScope } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { cn } from "@/lib/cn";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong";
}

/** Shared admin editor for the three `DropdownOption` scopes
 * (docs/design/custom-fields-admin-design.md §2.7): a `select`-type custom
 * field's options, task categories, and task priorities. Add / rename-label
 * / deactivate / reactivate — `value` is immutable after creation per the
 * backend contract, so "rename" only ever touches `label`. Built-in options
 * render their deactivate control disabled with an explanatory tooltip
 * instead of firing a request the backend is guaranteed to 409 on. */
export function DropdownOptionsEditor({
  scope,
  customFieldId,
  emptyLabel = "No options yet.",
}: {
  scope: DropdownOptionScope;
  customFieldId?: string;
  emptyLabel?: string;
}) {
  const [options, setOptions] = useState<DropdownOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newOption, setNewOption] = useState("");
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

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

  const handleAdd = async (e: FormEvent) => {
    e.preventDefault();
    if (!newOption.trim()) return;
    setAdding(true);
    try {
      const created = await api.createDropdownOption({
        scope,
        custom_field_id: customFieldId ?? null,
        value: newOption.trim(),
        label: newOption.trim(),
      });
      setOptions((prev) => [...prev, created]);
      setNewOption("");
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  };

  const handleSaveLabel = async (id: string) => {
    if (!editLabel.trim()) return;
    setBusyId(id);
    try {
      const updated = await api.updateDropdownOption(id, { label: editLabel.trim() });
      setOptions((prev) => prev.map((o) => (o.id === id ? updated : o)));
      setEditingId(null);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

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

      {loading ? (
        <p className="text-xs text-mute">Loading options…</p>
      ) : options.length === 0 ? (
        <p className="text-xs text-mute">{emptyLabel}</p>
      ) : (
        <ul className="space-y-1.5">
          {options.map((o) => (
            <li
              key={o.id}
              className={cn(
                "flex items-center justify-between gap-2 rounded-lg bg-canvas-soft px-3 py-1.5 text-sm",
                !o.is_active && "opacity-50"
              )}
            >
              {editingId === o.id ? (
                <>
                  <Input
                    value={editLabel}
                    onChange={(e) => setEditLabel(e.target.value)}
                    className="py-1"
                    autoFocus
                  />
                  <div className="flex shrink-0 gap-1.5">
                    <Button size="sm" variant="primary" onClick={() => handleSaveLabel(o.id)} disabled={busyId === o.id}>
                      Save
                    </Button>
                    <Button size="sm" variant="tertiary" onClick={() => setEditingId(null)} disabled={busyId === o.id}>
                      Cancel
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <span className="flex items-center gap-1.5 text-body">
                    {o.label}
                    {o.is_builtin && <Badge tone="gray">built-in</Badge>}
                    {!o.is_active && <Badge tone="red">inactive</Badge>}
                  </span>
                  <div className="flex shrink-0 gap-1.5">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        setEditingId(o.id);
                        setEditLabel(o.label);
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
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={handleAdd} className="flex gap-2">
        <Input
          placeholder="New option"
          value={newOption}
          onChange={(e) => setNewOption(e.target.value)}
          className="py-1.5"
        />
        <Button size="sm" variant="primary" type="submit" disabled={!newOption.trim() || adding}>
          + Add option
        </Button>
      </form>

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
