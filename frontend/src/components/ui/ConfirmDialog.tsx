"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";
import { Button } from "./Button";
import { Card } from "./Card";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: string;
  /** Optional form content rendered between the description and the
   * confirm/cancel actions — e.g. `TimerControls`'s manual-log form. Keeps
   * every "small form in a modal" surface in the app (delete confirm,
   * archive-instead offer, manual time log) on one shared shell instead of
   * a bespoke overlay per form. */
  children?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  busy?: boolean;
  /** Disables just the confirm action (e.g. an invalid form) without
   * changing it to the busy/"Working…" label. */
  confirmDisabled?: boolean;
  /** Override the default `max-w-sm` — a form with two date inputs side by
   * side needs a bit more room than a plain confirm/cancel prompt. */
  widthClassName?: string;
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
  children,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  busy = false,
  confirmDisabled = false,
  widthClassName = "max-w-sm",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  // Portal to <body> rather than rendering inline: some callers (e.g. a
  // manual-log dialog opened from a `TaskCard`) live inside an ancestor that
  // applies a CSS `transform` on hover (`hover:-translate-y-0.5`), which
  // creates a new containing block for `position: fixed` descendants — an
  // inline-rendered dialog would then be clipped/mispositioned relative to
  // that card instead of the viewport. Deferred to a `mounted` flag because
  // `document` doesn't exist during SSR.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!open || !mounted) return null;
  return createPortal(
    // React portals still bubble synthetic events up the *React* tree (not
    // just the DOM tree) to whatever component rendered this dialog — a
    // caller nested inside a clickable card (e.g. `TaskCard`'s
    // `onClick={() => board.selectTask(...)}`) would otherwise have every
    // click inside this dialog also re-trigger that ancestor's handler.
    // Stopping propagation here, once, is simpler and safer than requiring
    // every future caller to remember it on every button.
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        aria-label="Dismiss"
        onClick={onCancel}
        className="absolute inset-0 bg-ink/30 backdrop-blur-[2px]"
      />
      <Card
        role="alertdialog"
        aria-modal="true"
        className={cn("relative w-full p-5 shadow-2xl shadow-ink/25", widthClassName)}
      >
        <h3 className="text-base font-bold text-ink">{title}</h3>
        {description && <p className="mt-2 text-sm text-body">{description}</p>}
        {children && <div className="mt-4">{children}</div>}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="tertiary" size="sm" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "primary"}
            size="sm"
            onClick={onConfirm}
            disabled={busy || confirmDisabled}
          >
            {busy ? "Working…" : confirmLabel}
          </Button>
        </div>
      </Card>
    </div>,
    document.body
  );
}
