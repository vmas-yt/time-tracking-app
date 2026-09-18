"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { SWIMLANE_FIELDS } from "@/lib/types";
import type { BoardConfig, SwimlaneField } from "@/lib/types";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Select } from "@/components/ui/Input";

/** Single-setting screen — doesn't need a table, but gets its own
 * sub-nav destination per the restructuring brief rather than being buried
 * at the top of a long stacked page. */
export default function SwimLanesPage() {
  const [boardConfig, setBoardConfig] = useState<BoardConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getBoardConfig().then(setBoardConfig).catch((err) => setError(errorMessage(err)));
  }, []);

  const handleChange = async (value: SwimlaneField) => {
    try {
      const updated = await api.updateBoardConfig(value);
      setBoardConfig(updated);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Swim lanes</CardTitle>
      </CardHeader>
      <CardBody className="space-y-3">
        {error && (
          <p
            className="cursor-pointer rounded-xl bg-negative-bg px-4 py-2 text-sm text-canvas"
            onClick={() => setError(null)}
          >
            {error} <span className="opacity-70">(click to dismiss)</span>
          </p>
        )}
        <label className="flex items-center gap-3 text-sm text-body">
          Group board cards into swim lanes by
          <Select
            value={boardConfig?.swimlane_field ?? "assignee"}
            onChange={(e) => handleChange(e.target.value as SwimlaneField)}
            className="w-auto"
          >
            {SWIMLANE_FIELDS.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </Select>
        </label>
        <p className="text-xs text-mute">
          The five status columns (Backlog → To Do → In Progress → On Hold → Completed) are fixed and not
          configurable here — this setting only controls the horizontal grouping within each column.
        </p>
      </CardBody>
    </Card>
  );
}
