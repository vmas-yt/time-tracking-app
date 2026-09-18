"use client";

import { useEffect, useId } from "react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

// Mount order of every currently-open, Escape-listening SlideOver, shared
// across instances. A stacked pair (e.g. a custom field's "manage" panel
// with a nested "add option" panel on top of it) would otherwise each
// register their own unconditional `Escape -> onClose` listener and both
// fire on a single keypress, closing both layers at once instead of just
// the top one. Only the id at the end of this stack (the most recently
// opened panel) is allowed to act on Escape.
const escapeStack: string[] = [];

/** Shared right-side slide-over shell — the one interaction pattern for
 * "create/edit/view a thing" across the whole app (Add/Edit Task, task
 * detail, user profile, and every admin entity create/edit form). Extracted
 * from what used to be three separate copies of the same overlay + slide-in
 * markup (`AddTaskPanel`, `TaskDetailPanel`, `UserProfilePanel`) so every new
 * panel — admin or otherwise — gets the identical look or a deliberate,
 * reviewable diff instead of a fourth copy-paste.
 *
 * Stacks: nesting a second `SlideOver` (e.g. "manage options" opened from
 * inside a custom field's own panel) is supported via `layer` — layer 1 sits
 * above layer 0 at a higher z-index, mirroring how `ConfirmDialog` already
 * layers above every slide-over. */
export function SlideOver({
  open,
  onClose,
  children,
  widthClassName = "max-w-[480px]",
  panelClassName,
  closeLabel = "Close panel",
  layer = 0,
  disableEscapeClose = false,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  widthClassName?: string;
  panelClassName?: string;
  closeLabel?: string;
  layer?: 0 | 1;
  /** Skip the built-in Escape→close listener — for panels (like
   * `TaskDetailPanel`) that need Escape to do something other than an
   * unconditional close (e.g. exit edit mode first) and wire that up
   * themselves instead. */
  disableEscapeClose?: boolean;
}) {
  const id = useId();

  useEffect(() => {
    if (!open || disableEscapeClose) return;
    escapeStack.push(id);
    const onKey = (e: KeyboardEvent) => {
      // Only the topmost open panel closes on Escape — a stacked panel
      // beneath it should stay open until the one on top of it is gone.
      if (e.key === "Escape" && escapeStack[escapeStack.length - 1] === id) {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      const index = escapeStack.lastIndexOf(id);
      if (index !== -1) escapeStack.splice(index, 1);
    };
  }, [open, onClose, disableEscapeClose, id]);

  // Keep panels mounted only while open — matches the previous per-component
  // behavior (unmount on close) rather than introducing an exit-animation
  // change none of the callers asked for.
  if (!open) return null;

  return (
    <div className={cn("fixed inset-0 flex justify-end", layer === 0 ? "z-40" : "z-50")}>
      <button
        type="button"
        aria-label={closeLabel}
        onClick={onClose}
        className="absolute inset-0 bg-ink/30 backdrop-blur-[2px] animate-[fade-in_0.15s_ease-out]"
      />
      <div
        className={cn(
          "relative flex h-full w-full flex-col overflow-y-auto bg-canvas-soft shadow-2xl shadow-ink/25 animate-[slide-in_0.22s_cubic-bezier(0.16,1,0.3,1)]",
          widthClassName,
          panelClassName
        )}
      >
        {children}
      </div>
    </div>
  );
}

/** Common header row for a `SlideOver`: title block on the left, round close
 * button on the right, hairline border beneath. `children` carries the
 * title/subtitle/badges so callers with richer headers (e.g. `TaskDetailPanel`'s
 * status badges) aren't forced into a fixed title/subtitle prop shape. */
export function SlideOverHeader({
  onClose,
  children,
  borderClassName = "border-canvas",
}: {
  onClose: () => void;
  children: ReactNode;
  borderClassName?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 border-b px-6 py-5", borderClassName)}>
      {children}
      <button
        type="button"
        onClick={onClose}
        className="shrink-0 rounded-full p-1.5 text-mute hover:bg-canvas hover:text-ink"
        aria-label="Close"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  );
}
