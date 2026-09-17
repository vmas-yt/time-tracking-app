"use client";

import { Button } from "./Button";
import { Card } from "./Card";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Shared modal confirmation, used for every irreversible/destructive action
 * added by docs/design/custom-fields-admin-design.md §5.3 (delete task,
 * remove custom field, deactivate a dropdown option, delete a project) —
 * centralizing it here so "confirm before destructive action" is one
 * component, not five copy-pasted `window.confirm`s. Wise-Inspired-design-
 * analysis tokens: canvas card, rounded-xl, ink/30 backdrop matching the
 * slide-over panels' overlay treatment. */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Dismiss"
        onClick={onCancel}
        className="absolute inset-0 bg-ink/30 backdrop-blur-[2px]"
      />
      <Card role="alertdialog" aria-modal="true" className="relative w-full max-w-sm p-5 shadow-2xl shadow-ink/25">
        <h3 className="text-base font-bold text-ink">{title}</h3>
        {description && <p className="mt-2 text-sm text-body">{description}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="tertiary" size="sm" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant={tone === "danger" ? "danger" : "primary"} size="sm" onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : confirmLabel}
          </Button>
        </div>
      </Card>
    </div>
  );
}
