"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { ManualEntrySettings } from "@/lib/types";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

/** Single-setting screen for the manual/retroactive time-logging policy —
 * same shape as `swim-lanes/page.tsx` (a single admin-configurable value,
 * no table/SlideOver needed). Unlike swim lanes' `<Select>` (which saves on
 * every change), this is a free-typed number, so it needs an explicit Save
 * action plus dirty-state tracking rather than saving on every keystroke. */
export default function ManualTimeSettingsPage() {
  const [settings, setSettings] = useState<ManualEntrySettings | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .getManualEntrySettings()
      .then((s) => {
        setSettings(s);
        setDraft(String(s.max_days_back));
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  const parsed = Number(draft);
  const isValid = draft.trim() !== "" && Number.isInteger(parsed) && parsed >= 0;
  const isDirty = settings != null && draft.trim() !== "" && parsed !== settings.max_days_back;

  const handleSave = async () => {
    if (!isValid) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateManualEntrySettings(parsed);
      setSettings(updated);
      setDraft(String(updated.max_days_back));
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Manual time settings</CardTitle>
        <p className="mt-1 text-xs text-mute">
          Controls how far back an employee may backdate a manually-logged task or time entry (the
          &ldquo;Log time manually&rdquo; flow). A value of 0 means only today&rsquo;s date is allowed — no
          backdating.
        </p>
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
        {loading ? (
          <p className="text-sm text-mute">Loading…</p>
        ) : (
          <>
            <label className="flex items-center gap-3 text-sm text-body">
              Maximum days back allowed
              <Input
                type="number"
                min={0}
                step={1}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className="w-24"
              />
            </label>
            {!isValid && draft.trim() !== "" && (
              <p className="text-xs text-negative">Enter a whole number of 0 or more.</p>
            )}
            <div className="flex items-center gap-3">
              <Button variant="primary" size="sm" onClick={handleSave} disabled={!isValid || !isDirty || saving}>
                {saving ? "Saving…" : "Save"}
              </Button>
              {saved && <span className="text-xs text-mute">Saved.</span>}
              {settings && (
                <span className="text-xs text-mute">
                  Last updated {new Date(settings.updated_at).toLocaleString()}
                </span>
              )}
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}
