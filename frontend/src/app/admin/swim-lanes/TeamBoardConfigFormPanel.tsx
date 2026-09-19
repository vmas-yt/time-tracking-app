"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { SWIMLANE_FIELDS } from "@/lib/types";
import type { SwimlaneField, Team, TeamBoardConfig } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";

/** Edit slide-over for one team's board — the per-team analogue of the
 * global setting's single `<Select>` (docs/design/team-scoped-boards-design.md
 * §6.2). Two independent fields: `board_name` (a display label only,
 * deliberately separate from `Team.name` — §3) and `swimlane_field` (same
 * enum/options as the global setting). Only ever opened for a row the caller
 * already confirmed `can_manage` for (the table's own Edit button is
 * disabled otherwise), but the backend re-checks on `PATCH` regardless. */
export function TeamBoardConfigFormPanel({
  open,
  team,
  config,
  onClose,
  onSaved,
}: {
  open: boolean;
  team: Team | null;
  config: TeamBoardConfig | null;
  onClose: () => void;
  onSaved: (config: TeamBoardConfig) => void;
}) {
  const [boardName, setBoardName] = useState("");
  const [swimlaneField, setSwimlaneFieldValue] = useState<SwimlaneField>("assignee");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setBoardName(config?.board_name ?? "");
    setSwimlaneFieldValue(config?.swimlane_field ?? "assignee");
    setError(null);
  }, [open, config]);

  if (!open || !team) return null;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const trimmed = boardName.trim();
      const updated = await api.updateTeamBoardConfig(team.id, {
        // Explicit `null` clears back to the `Team.name` fallback (§4.2) —
        // an admin blanking the field out is "unrename it," not "leave it
        // unchanged."
        board_name: trimmed.length > 0 ? trimmed : null,
        swimlane_field: swimlaneField,
      });
      onSaved(updated);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SlideOver open={open} onClose={onClose} widthClassName="max-w-[440px]">
      <SlideOverHeader onClose={onClose}>
        <div>
          <h2 className="text-lg font-bold tracking-tight text-ink">Edit {team.name}&rsquo;s board</h2>
          <p className="mt-1 text-xs text-mute">
            These settings only affect {team.name}&rsquo;s own board — not the all-teams/unscoped board, and not any
            other team&rsquo;s.
          </p>
        </div>
      </SlideOverHeader>
      <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 p-6">
        {error && <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{error}</p>}

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Board name</span>
          <Input
            value={boardName}
            onChange={(e) => setBoardName(e.target.value)}
            placeholder={team.name}
            autoFocus
          />
          <span className="block text-xs text-mute">
            Purely a display label for the Kanban board and team switcher — leave blank to just show &ldquo;
            {team.name}&rdquo;. This never renames the team itself.
          </span>
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-semibold text-ink">Group lanes by</span>
          <Select value={swimlaneField} onChange={(e) => setSwimlaneFieldValue(e.target.value as SwimlaneField)}>
            {SWIMLANE_FIELDS.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </Select>
        </label>

        <div className="mt-auto flex gap-2 border-t border-canvas pt-4">
          <Button variant="primary" type="submit" disabled={submitting} className="flex-1">
            {submitting ? "Saving…" : "Save changes"}
          </Button>
          <Button variant="tertiary" type="button" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
        </div>
      </form>
    </SlideOver>
  );
}
