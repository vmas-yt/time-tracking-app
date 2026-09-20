"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type { ManualEntrySettings, TaskCategory, TaskPriority, TaskType } from "@/lib/types";
import { TASK_CATEGORIES, TASK_PRIORITIES } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";
import { useBoard } from "@/board/store";
import { activeOptions } from "@/lib/options";
import { cn } from "@/lib/cn";
import {
  fetchManualEntrySettings,
  todayDateString,
  toDurationMinutes,
  validateManualLog,
  type ManualLogDraft,
} from "@/board/manualLog";
import { CustomFieldInput } from "./CustomFieldInput";
import { ManualLogFields } from "./ManualLogFields";

type CreateMode = "live" | "manual";

/** Right-side slide-over for task creation — replaces the old inline
 * `NewTaskForm` at the top of the board (design doc §14 item 4). Same
 * fields, same `board.createTask(...)` call; pure presentation change.
 * Built on the shared `SlideOver` primitive so every "panel from the right"
 * surface in this app — task add/edit, task detail, admin entities — shares
 * one implementation. */
export function AddTaskPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const board = useBoard();
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<TaskCategory>("meeting");
  const [categoryOtherText, setCategoryOtherText] = useState("");
  const [taskType, setTaskType] = useState<TaskType>("normal");
  const [priority, setPriority] = useState<TaskPriority>("normal");
  const [assigneeId, setAssigneeId] = useState<string>(board.currentUserId);
  const [projectId, setProjectId] = useState<string>("");
  const [description, setDescription] = useState("");
  const [customValues, setCustomValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  // ---- Manual/retroactive time logging (docs/PRD.md) ---------------------
  // "Log time already worked" is a mode switch on the same form, not a
  // separate panel — same task fields, three extra date/duration inputs,
  // different submit endpoint.
  const [mode, setMode] = useState<CreateMode>("live");
  const [manualDraft, setManualDraft] = useState<ManualLogDraft>({
    startDate: todayDateString(),
    completionDate: todayDateString(),
    hours: 0,
    minutes: 0,
  });
  const [manualSettings, setManualSettings] = useState<ManualEntrySettings | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);

  const categoryChoices = board.categoryOptions.length
    ? activeOptions(board.categoryOptions)
    : TASK_CATEGORIES.map((c) => ({ value: c.key, label: c.label }));
  const priorityChoices = board.priorityOptions.length
    ? activeOptions(board.priorityOptions)
    : TASK_PRIORITIES.map((p) => ({ value: p.key, label: p.label }));

  useEffect(() => {
    if (!open) return;
    setAssigneeId(board.currentUserId);
    setProjectId(board.projectId ?? "");
    setCategory((categoryChoices.find((c) => c.value === "meeting")?.value ?? categoryChoices[0]?.value ?? "meeting") as TaskCategory);
    setPriority((priorityChoices.find((p) => p.value === "normal")?.value ?? priorityChoices[0]?.value ?? "normal") as TaskPriority);
    setCustomValues({});
    setMode("live");
    setManualDraft({ startDate: todayDateString(), completionDate: todayDateString(), hours: 0, minutes: 0 });
    setManualError(null);
    fetchManualEntrySettings()
      .then(setManualSettings)
      .catch(() => {
        // Non-fatal — the form still works with only the server-side bound
        // enforced (no client-side min-date/inline hint until this resolves).
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const resetAndClose = () => {
    setTitle("");
    setCategoryOtherText("");
    setTaskType("normal");
    setDescription("");
    setProjectId("");
    setCustomValues({});
    setMode("live");
    setManualError(null);
    onClose();
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    if (category === "other" && !categoryOtherText.trim()) return;

    const basePayload = {
      title: title.trim(),
      description: description.trim() || undefined,
      category,
      category_other_text: category === "other" ? categoryOtherText.trim() : undefined,
      task_type: taskType,
      priority,
      // A manual entry always attributes its TimeEntry to whoever submits
      // it (create_manual_entry backend-side), so it's forced to yourself
      // here regardless of what the (disabled, in this mode) Assignee
      // select last held — matching the disabled select's displayed value.
      assignee_id: (mode === "manual" ? board.currentUserId : assigneeId) || null,
      project_id: projectId || null,
      custom_values: customValues,
    };

    if (mode === "manual") {
      const err = validateManualLog(manualDraft, manualSettings?.max_days_back ?? null);
      if (err) {
        setManualError(err);
        return;
      }
      setManualError(null);
      setSubmitting(true);
      const created = await board.createManualTask({
        ...basePayload,
        start_date: manualDraft.startDate,
        completion_date: manualDraft.completionDate,
        duration_minutes: toDurationMinutes(manualDraft),
      });
      setSubmitting(false);
      if (created) resetAndClose();
      return;
    }

    setSubmitting(true);
    const created = await board.createTask(basePayload);
    setSubmitting(false);
    if (created) resetAndClose();
  };

  return (
    <SlideOver
      open={open}
      onClose={resetAndClose}
      widthClassName="max-w-[480px]"
      panelClassName="bg-canvas"
      closeLabel="Close new task panel"
    >
      <SlideOverHeader onClose={resetAndClose} borderClassName="border-canvas-soft">
        <div>
          <h2 className="text-lg font-bold tracking-tight text-ink">New task</h2>
          <p className="mt-1 text-xs text-mute">
            Employees mostly create and start their own tasks — assignee defaults to you.
          </p>
        </div>
      </SlideOverHeader>

      <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 p-6">
          <div role="tablist" aria-label="Task creation mode" className="flex gap-1 rounded-xl bg-canvas-soft p-1">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "live"}
              onClick={() => setMode("live")}
              className={cn(
                "flex-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors",
                mode === "live" ? "bg-canvas text-ink" : "text-mute hover:text-ink"
              )}
            >
              Create task
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "manual"}
              onClick={() => setMode("manual")}
              className={cn(
                "flex-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors",
                mode === "manual" ? "bg-canvas text-ink" : "text-mute hover:text-ink"
              )}
            >
              Log time already worked
            </button>
          </div>

          <label className="space-y-1.5 text-sm">
            <span className="font-semibold text-ink">Title</span>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Task title"
              autoFocus
            />
          </label>

          <label className="space-y-1.5 text-sm">
            <span className="font-semibold text-ink">Category</span>
            <Select value={category} onChange={(e) => setCategory(e.target.value as TaskCategory)}>
              {categoryChoices.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
          </label>

          {category === "other" && (
            <label className="space-y-1.5 text-sm">
              <span className="font-semibold text-ink">Describe category</span>
              <Input
                value={categoryOtherText}
                onChange={(e) => setCategoryOtherText(e.target.value)}
                placeholder="Describe category"
              />
            </label>
          )}

          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-1.5 text-sm">
              <span className="font-semibold text-ink">Type</span>
              <Select value={taskType} onChange={(e) => setTaskType(e.target.value as TaskType)}>
                <option value="normal">Normal</option>
                <option value="ad_hoc">Ad-hoc</option>
              </Select>
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="font-semibold text-ink">Priority</span>
              <Select value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)}>
                {priorityChoices.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </Select>
            </label>
          </div>

          <label className="space-y-1.5 text-sm">
            <span className="font-semibold text-ink">Assignee</span>
            <Select
              value={mode === "manual" ? board.currentUserId : assigneeId}
              onChange={(e) => setAssigneeId(e.target.value)}
              disabled={mode === "manual"}
            >
              {board.activeUsers.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.id === board.currentUserId ? `${u.full_name} (me)` : u.full_name}
                </option>
              ))}
            </Select>
            {mode === "manual" && (
              <p className="text-xs text-mute">
                A manual entry always logs time for yourself — the backend attributes it to whoever submits it.
              </p>
            )}
          </label>

          <label className="space-y-1.5 text-sm">
            <span className="font-semibold text-ink">Project</span>
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">No project (standalone)</option>
              {board.projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </label>

          {mode === "manual" && (
            <div className="space-y-3 rounded-xl bg-canvas-soft p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-mute">
                Time already worked on this task
              </p>
              <ManualLogFields
                draft={manualDraft}
                onChange={setManualDraft}
                maxDaysBack={manualSettings?.max_days_back ?? null}
                error={manualError}
              />
            </div>
          )}

          <label className="flex flex-1 flex-col space-y-1.5 text-sm">
            <span className="font-semibold text-ink">Description (optional)</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Add any context…"
              rows={4}
              className="w-full flex-1 rounded-md border border-ink bg-canvas px-4 py-2.5 text-sm text-ink placeholder:text-mute focus:outline-none focus:ring-2 focus:ring-primary-neutral"
            />
          </label>

          {board.customFields.length > 0 && (
            <div className="space-y-3 border-t border-canvas-soft pt-4">
              <span className="text-sm font-semibold text-ink">Custom fields</span>
              {board.customFields.map((field) => (
                <label key={field.id} className="block space-y-1.5 text-sm">
                  <span className="text-ink">{field.name}</span>
                  <CustomFieldInput
                    field={field}
                    value={customValues[field.id] ?? ""}
                    onChange={(value) => setCustomValues((prev) => ({ ...prev, [field.id]: value }))}
                  />
                </label>
              ))}
            </div>
          )}

          <div className="mt-auto flex gap-2 border-t border-canvas-soft pt-4">
            <Button variant="primary" type="submit" disabled={!title.trim() || submitting} className="flex-1">
              {submitting
                ? mode === "manual"
                  ? "Logging…"
                  : "Creating…"
                : mode === "manual"
                  ? "Log manual entry"
                  : "Create task"}
            </Button>
            <Button variant="tertiary" type="button" onClick={resetAndClose}>
              Cancel
            </Button>
          </div>
        </form>
    </SlideOver>
  );
}
