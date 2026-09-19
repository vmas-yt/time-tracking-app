"use client";

import { Input } from "@/components/ui/Input";
import { daysAgoDateString, todayDateString, type ManualLogDraft } from "@/board/manualLog";

interface ManualLogFieldsProps {
  draft: ManualLogDraft;
  onChange: (next: ManualLogDraft) => void;
  /** `null` while `GET /admin/manual-entry-settings` is still loading —
   * shows a neutral "checking…" hint instead of a bound the picker can't
   * enforce yet. */
  maxDaysBack: number | null;
  error?: string | null;
}

/**
 * The three inputs shared by both manual-log entry points (a brand-new task
 * in `AddTaskPanel`, an existing not-yet-started task via `TimerControls`):
 * Start Date, Completion Date — independently editable, both default to
 * today, changing one never touches the other — and Duration, split into
 * hours/minutes for a friendlier input than one raw minutes field.
 */
export function ManualLogFields({ draft, onChange, maxDaysBack, error }: ManualLogFieldsProps) {
  const today = todayDateString();
  const minDate = maxDaysBack != null ? daysAgoDateString(maxDaysBack) : undefined;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Start date</span>
          <Input
            type="date"
            value={draft.startDate}
            min={minDate}
            max={today}
            onChange={(e) => onChange({ ...draft, startDate: e.target.value })}
          />
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Completion date</span>
          <Input
            type="date"
            value={draft.completionDate}
            min={minDate}
            max={today}
            onChange={(e) => onChange({ ...draft, completionDate: e.target.value })}
          />
        </label>
      </div>

      <div className="space-y-1.5 text-sm">
        <span className="font-semibold text-ink">Duration worked</span>
        <div className="flex items-center gap-2">
          <Input
            type="number"
            min={0}
            aria-label="Hours"
            value={draft.hours}
            onChange={(e) => onChange({ ...draft, hours: Number(e.target.value) })}
            className="w-20"
          />
          <span className="text-xs text-mute">h</span>
          <Input
            type="number"
            min={0}
            max={59}
            aria-label="Minutes"
            value={draft.minutes}
            onChange={(e) => onChange({ ...draft, minutes: Number(e.target.value) })}
            className="w-20"
          />
          <span className="text-xs text-mute">m</span>
        </div>
      </div>

      <p className="text-xs text-mute">
        {maxDaysBack != null
          ? `You can log time up to ${maxDaysBack} day${maxDaysBack === 1 ? "" : "s"} back.`
          : "Checking how far back you're allowed to log…"}
      </p>

      {error && <p className="rounded-lg bg-negative-bg px-3 py-2 text-xs text-canvas">{error}</p>}
    </div>
  );
}
