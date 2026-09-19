"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { SWIMLANE_FIELDS } from "@/lib/types";
import type { BoardConfig, SwimlaneField, Team, TeamBoardConfig } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Select } from "@/components/ui/Input";
import { TeamBoardConfigFormPanel } from "./TeamBoardConfigFormPanel";

const fieldLabel = (key: SwimlaneField) => SWIMLANE_FIELDS.find((f) => f.key === key)?.label ?? key;

/** List+detail rework (docs/design/team-scoped-boards-design.md §6.2):
 * one row per active team's own board (`TeamBoardConfig`, Round C) plus one
 * fixed row for the pre-existing global `BoardConfig` — kept as its own,
 * visually distinct section rather than folded into the table, since it's a
 * completely separate setting (the "all tasks / no team" board, §1.2/§4.3),
 * not a row that happens to also be a team. */
export default function SwimLanesPage() {
  const [globalConfig, setGlobalConfig] = useState<BoardConfig | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [teamConfigs, setTeamConfigs] = useState<Record<string, TeamBoardConfig>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingTeam, setEditingTeam] = useState<Team | null>(null);
  const [globalSaving, setGlobalSaving] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([api.getBoardConfig(), api.listTeams()])
      .then(async ([config, teamList]) => {
        setGlobalConfig(config);
        setTeams(teamList);
        const configs = await Promise.all(teamList.map((t) => api.getTeamBoardConfig(t.id)));
        setTeamConfigs(Object.fromEntries(configs.map((c) => [c.team_id, c] as const)));
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleGlobalChange = async (value: SwimlaneField) => {
    setGlobalSaving(true);
    try {
      const updated = await api.updateBoardConfig(value);
      setGlobalConfig(updated);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setGlobalSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      {error && (
        <p className="cursor-pointer rounded-xl bg-negative-bg px-4 py-2 text-sm text-canvas" onClick={() => setError(null)}>
          {error} <span className="opacity-70">(click to dismiss)</span>
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>All teams / unscoped board</CardTitle>
          <p className="mt-1 text-xs text-mute">
            Grouping for the default board view — tasks with no team, or the board when no team is selected. This is
            a separate, app-wide setting from any individual team&rsquo;s board below; it has no board-name concept of
            its own.
          </p>
        </CardHeader>
        <CardBody className="space-y-3">
          <label
            className="flex items-center gap-3 text-sm text-body"
            title={
              globalConfig && !globalConfig.can_manage
                ? "You don't have permission to change swim-lane grouping."
                : undefined
            }
          >
            Group board cards into swim lanes by
            <Select
              value={globalConfig?.swimlane_field ?? "assignee"}
              onChange={(e) => handleGlobalChange(e.target.value as SwimlaneField)}
              disabled={!globalConfig || !globalConfig.can_manage || globalSaving}
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

      <Card>
        <CardHeader>
          <CardTitle>Team boards</CardTitle>
          <p className="mt-1 text-xs text-mute">
            Every active team has its own board — its own swim-lane grouping and, optionally, its own display name
            (independent of the team&rsquo;s own name).
          </p>
        </CardHeader>
        <CardBody className="space-y-4">
          {loading ? (
            <p className="text-sm text-mute">Loading teams…</p>
          ) : teams.length === 0 ? (
            <p className="text-sm text-mute">No active teams yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-mute/20 text-left text-xs uppercase text-mute">
                    <th className="py-2 font-semibold">Name</th>
                    <th className="py-2 font-semibold">Board name</th>
                    <th className="py-2 font-semibold">Swim-lane field</th>
                    <th className="py-2 font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {teams.map((t) => {
                    const config: TeamBoardConfig | undefined = teamConfigs[t.id];
                    const canManage = config?.can_manage ?? false;
                    return (
                      <tr key={t.id} className="border-b border-canvas-soft last:border-0">
                        <td className="py-2 font-medium text-ink">{t.name}</td>
                        <td className="py-2 text-body">
                          {config?.board_name ? (
                            config.board_name
                          ) : (
                            <span className="text-mute">— (using team name)</span>
                          )}
                        </td>
                        <td className="py-2 text-body">
                          {config ? (
                            fieldLabel(config.swimlane_field)
                          ) : (
                            <Badge tone="gray">Loading…</Badge>
                          )}
                        </td>
                        <td className="py-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={!config || !canManage}
                            title={
                              config && !canManage
                                ? "You don't have permission to change this team's board."
                                : undefined
                            }
                            onClick={() => setEditingTeam(t)}
                          >
                            Edit
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>

      <TeamBoardConfigFormPanel
        open={editingTeam !== null}
        team={editingTeam}
        config={editingTeam ? teamConfigs[editingTeam.id] ?? null : null}
        onClose={() => setEditingTeam(null)}
        onSaved={(updated) => {
          setTeamConfigs((prev) => ({ ...prev, [updated.team_id]: updated }));
          setEditingTeam(null);
        }}
      />
    </div>
  );
}
