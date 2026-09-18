"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { CustomField, CustomFieldType } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";
import { DropdownOptionsTable } from "../shared/DropdownOptionsTable";

/** Create/manage slide-over for a custom field.
 *
 * "Create" mode posts name + type, exactly like the old inline form (the
 * backend's `POST /admin/custom-fields` never received an `options` payload
 * from this UI before, so this preserves that behavior rather than adding
 * new capability).
 *
 * "Manage" mode (opened from the field's row in the table) now supports
 * renaming via `PATCH /admin/custom-fields/{id}` (name-only — an inline
 * Save button next to the name field, enabled only once the draft differs
 * from the saved name). Type stays a disabled `<Input>` — the backend
 * deliberately never accepts `field_type` on update, since changing a
 * field's data type after real values exist is out of scope — and, for
 * `select`-type fields, this panel still embeds the same
 * `DropdownOptionsTable` used by Categories/Priorities so option management
 * lives behind this one slide-over pattern instead of the old inline-expand
 * row. */
export function CustomFieldFormPanel({
  open,
  mode,
  field,
  onClose,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "manage";
  field: CustomField | null;
  onClose: () => void;
  onSaved: (field: CustomField, opts: { created: boolean }) => void;
}) {
  const [name, setName] = useState("");
  const [fieldType, setFieldType] = useState<CustomFieldType>("text");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // "Manage" mode's own draft for the rename flow — kept separate from
  // `name` above (which create mode owns) so switching panels never bleeds
  // state between the two forms.
  const [nameDraft, setNameDraft] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [nameSaved, setNameSaved] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (mode === "create") {
      setName("");
      setFieldType("text");
      setError(null);
    } else if (field) {
      setNameDraft(field.name);
      setNameError(null);
      setNameSaved(false);
    }
    // Keyed on `field?.id`, not `field` itself: a successful rename replaces
    // `field` with a new object (same id) so the slide-over header picks up
    // the new name, but re-running this reset on that same swap would wipe
    // `nameSaved` back to false before the "Saved." confirmation ever
    // rendered. Only a real switch — opening the panel, or managing a
    // different field — should reset the draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode, field?.id]);

  if (!open) return null;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.createCustomField({ name: name.trim(), field_type: fieldType });
      onSaved(created, { created: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const trimmedDraft = nameDraft.trim();
  const canSaveName = field != null && trimmedDraft.length > 0 && trimmedDraft !== field.name;

  const handleSaveName = async () => {
    if (!field || !canSaveName) return;
    setSavingName(true);
    setNameError(null);
    setNameSaved(false);
    try {
      const updated = await api.updateCustomField(field.id, { name: trimmedDraft });
      onSaved(updated, { created: false });
      setNameDraft(updated.name);
      setNameSaved(true);
    } catch (err) {
      setNameError(errorMessage(err));
    } finally {
      setSavingName(false);
    }
  };

  return (
    <SlideOver open={open} onClose={onClose} widthClassName="max-w-[480px]">
      <SlideOverHeader onClose={onClose}>
        <div>
          <h2 className="text-lg font-bold tracking-tight text-ink">
            {mode === "create" ? "Add custom field" : field?.name ?? "Custom field"}
          </h2>
          {mode === "manage" && field && (
            <div className="mt-1.5 flex items-center gap-1.5">
              <Badge>{field.field_type}</Badge>
            </div>
          )}
        </div>
      </SlideOverHeader>

      <div className="flex flex-1 flex-col gap-4 p-6">
        {error && <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{error}</p>}

        {mode === "create" ? (
          <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4">
            <label className="space-y-1.5 text-sm">
              <span className="font-semibold text-ink">Field name</span>
              <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Client" />
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="font-semibold text-ink">Type</span>
              <Select value={fieldType} onChange={(e) => setFieldType(e.target.value as CustomFieldType)}>
                <option value="text">Text</option>
                <option value="number">Number</option>
                <option value="select">Select</option>
                <option value="date">Date</option>
                <option value="boolean">Boolean</option>
              </Select>
            </label>
            {fieldType === "select" && (
              <p className="text-xs text-mute">
                You&rsquo;ll add this field&rsquo;s options after creating it, from its row in the table.
              </p>
            )}
            <div className="mt-auto flex gap-2 border-t border-canvas pt-4">
              <Button variant="primary" type="submit" disabled={!name.trim() || submitting} className="flex-1">
                {submitting ? "Creating…" : "Create field"}
              </Button>
              <Button variant="tertiary" type="button" onClick={onClose} disabled={submitting}>
                Cancel
              </Button>
            </div>
          </form>
        ) : field ? (
          <div className="space-y-4">
            <div className="space-y-1.5 text-sm">
              <span className="font-semibold text-ink">Field name</span>
              <div className="flex gap-2">
                <Input
                  value={nameDraft}
                  onChange={(e) => {
                    setNameDraft(e.target.value);
                    setNameSaved(false);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleSaveName();
                    }
                  }}
                  className="flex-1"
                />
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={handleSaveName}
                  disabled={!canSaveName || savingName}
                >
                  {savingName ? "Saving…" : "Save"}
                </Button>
              </div>
              {nameError && <p className="text-xs text-negative">{nameError}</p>}
              {nameSaved && !nameError && <p className="text-xs text-positive">Saved.</p>}
            </div>
            <label className="space-y-1.5 text-sm">
              <span className="font-semibold text-ink">Type</span>
              <Input value={field.field_type} disabled />
            </label>
            <p className="text-xs text-mute">
              Type can&rsquo;t be changed after creation — remove and re-create the field instead.
            </p>

            {field.field_type === "select" && (
              <div className="space-y-2 border-t border-canvas pt-4">
                <span className="text-sm font-semibold text-ink">Options</span>
                <DropdownOptionsTable
                  scope="custom_field"
                  customFieldId={field.id}
                  emptyLabel="No options yet — add at least one before using this field on a task."
                  panelLayer={1}
                />
              </div>
            )}
          </div>
        ) : null}
      </div>
    </SlideOver>
  );
}
