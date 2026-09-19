import { api } from "@/lib/api";
import type { ManualEntrySettings } from "@/lib/types";

// ---------------------------------------------------------------------------
// Pure date helpers + client-side validation for the manual/retroactive
// time-logging flow (docs/PRD.md's manual-log feature). Mirrors the shape of
// `board/engine.ts`: no I/O here except the tiny cached settings fetcher
// below — the backend (`services/tasks.py::validate_manual_entry_dates`) is
// still the authority and re-validates every submission independently of
// whatever this file allows through.
// ---------------------------------------------------------------------------

/** Today's date as a `YYYY-MM-DD` string in the viewer's local timezone —
 * the native value shape of an HTML `<input type="date">`. */
export function todayDateString(): string {
  return toDateString(new Date());
}

/** `days` days before today, as a `YYYY-MM-DD` string — used as an
 * `<input type="date" min=...>` bound once the admin's window is known. */
export function daysAgoDateString(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return toDateString(d);
}

function toDateString(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export interface ManualLogDraft {
  startDate: string;
  completionDate: string;
  /** Hours/minutes are kept split in the UI (friendlier than one raw
   * minutes field) and combined into `duration_minutes` only at submit. */
  hours: number;
  minutes: number;
}

export function toDurationMinutes(draft: Pick<ManualLogDraft, "hours" | "minutes">): number {
  const hours = Number.isFinite(draft.hours) ? Math.max(0, Math.floor(draft.hours)) : 0;
  const minutes = Number.isFinite(draft.minutes) ? Math.max(0, Math.floor(draft.minutes)) : 0;
  return hours * 60 + minutes;
}

/**
 * Client-side mirror of the backend's own checks — a UX nicety (fail fast,
 * explain why) layered on top of, never instead of, server-side validation.
 * `maxDaysBack` of `null` means "not loaded yet"; the date-window check is
 * skipped until it resolves rather than blocking on a slow settings fetch.
 */
export function validateManualLog(draft: ManualLogDraft, maxDaysBack: number | null): string | null {
  if (!draft.startDate || !draft.completionDate) {
    return "Start and completion dates are required.";
  }
  const start = new Date(`${draft.startDate}T00:00:00`);
  const completion = new Date(`${draft.completionDate}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  if (start > today || completion > today) {
    return "Dates can't be in the future.";
  }
  if (completion < start) {
    return "Completion date can't be before the start date.";
  }
  if (maxDaysBack != null) {
    const earliestAllowed = new Date(today);
    earliestAllowed.setDate(earliestAllowed.getDate() - maxDaysBack);
    if (start < earliestAllowed) {
      return `Start date can't be more than ${maxDaysBack} day${maxDaysBack === 1 ? "" : "s"} back.`;
    }
  }
  if (toDurationMinutes(draft) <= 0) {
    return "Enter a duration greater than zero.";
  }
  return null;
}

// ---- Cached settings fetch -------------------------------------------------
// Every eligible task card on the board could in principle open the manual-
// log affordance, so a naive `useEffect` fetch per component instance would
// fire one GET per visible card the moment it renders. This module-level
// cache means the first component that actually needs the setting (opening
// the form, not just rendering the button) fetches it once per page load;
// everyone else reuses the same in-flight/resolved promise.
let cached: ManualEntrySettings | null = null;
let inFlight: Promise<ManualEntrySettings> | null = null;

export function fetchManualEntrySettings(): Promise<ManualEntrySettings> {
  if (cached) return Promise.resolve(cached);
  if (!inFlight) {
    inFlight = api
      .getManualEntrySettings()
      .then((settings) => {
        cached = settings;
        inFlight = null;
        return settings;
      })
      .catch((err) => {
        inFlight = null;
        throw err;
      });
  }
  return inFlight;
}
