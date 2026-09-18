"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { DropdownOption, DropdownOptionScope } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";

/** Create/rename slide-over for a single `DropdownOption` row — shared by
 * the Categories page, the Priorities page, and a select-type custom
 * field's options section. Replaces `DropdownOptionsEditor`'s old inline
 * add-row (`value`/`label` both set to the same typed string, exactly as
 * before) and inline rename-in-place (only `label` is ever sent — `value`
 * is immutable after creation per the backend contract, so an existing
 * option's value renders read-only here rather than editable). Layered at
 * `layer=1` so it can be opened from inside a custom field's own panel. */
export function DropdownOptionFormPanel({
  open,
  scope,
  customFieldId,
  option,
  layer = 0,
  onClose,
  onSaved,
}: {
  open: boolean;
  scope: DropdownOptionScope;
  customFieldId?: string;
  option: DropdownOption | null;
  layer?: 0 | 1;
  onClose: () => void;
  onSaved: (option: DropdownOption, opts: { created: boolean }) => void;
}) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isEdit = option !== null;

  useEffect(() => {
    if (!open) return;
    setName(isEdit ? option!.label : "");
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, option?.id]);

  if (!open) return null;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      if (isEdit) {
        const updated = await api.updateDropdownOption(option!.id, { label: name.trim() });
        onSaved(updated, { created: false });
      } else {
        const created = await api.createDropdownOption({
          scope,
          custom_field_id: customFieldId ?? null,
          value: name.trim(),
          label: name.trim(),
        });
        onSaved(created, { created: true });
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SlideOver open={open} onClose={onClose} widthClassName="max-w-[400px]" layer={layer}>
      <SlideOverHeader onClose={onClose}>
        <div>
          <h2 className="text-lg font-bold tracking-tight text-ink">{isEdit ? "Rename option" : "Add option"}</h2>
        </div>
      </SlideOverHeader>
      <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 p-6">
        {error && <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{error}</p>}
        {isEdit && (
          <p className="rounded-xl bg-canvas px-3 py-2 text-xs text-mute">
            Stored value <span className="font-mono text-body">{option!.value}</span> can&rsquo;t change — only the
            display label can be renamed.
          </p>
        )}
        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">{isEdit ? "Label" : "Option name"}</span>
          <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Onboarding" />
        </label>
        <div className="mt-auto flex gap-2 border-t border-canvas pt-4">
          <Button variant="primary" type="submit" disabled={!name.trim() || submitting} className="flex-1">
            {submitting ? "Saving…" : isEdit ? "Save" : "Add option"}
          </Button>
          <Button variant="tertiary" type="button" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
        </div>
      </form>
    </SlideOver>
  );
}
