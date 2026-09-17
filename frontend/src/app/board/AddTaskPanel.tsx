"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type { TaskCategory, TaskPriority, TaskType } from "@/lib/types";
import { TASK_CATEGORIES } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { useBoard } from "@/board/store";

/** Right-side slide-over for task creation — replaces the old inline
 * `NewTaskForm` at the top of the board (design doc §14 item 4). Same
 * fields, same `board.createTask(...)` call; pure presentation change.
 * Mirrors `TaskDetailPanel`'s overlay + slide-in interaction pattern so the
 * two "panel from the right" surfaces in this app feel consistent. */
export function AddTaskPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const board = useBoard();
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<TaskCategory>("meeting");
  const [categoryOtherText, setCategoryOtherText] = useState("");
  const [taskType, setTaskType] = useState<TaskType>("normal");
  const [priority, setPriority] = useState<TaskPriority>("normal");
  const [assigneeId, setAssigneeId] = useState<string>(board.currentUserId);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) setAssigneeId(board.currentUserId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const resetAndClose = () => {
    setTitle("");
    setCategory("meeting");
    setCategoryOtherText("");
    setTaskType("normal");
    setPriority("normal");
    setDescription("");
    onClose();
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    if (category === "other" && !categoryOtherText.trim()) return;
    setSubmitting(true);
    const created = await board.createTask({
      title: title.trim(),
      description: description.trim() || undefined,
      category,
      category_other_text: category === "other" ? categoryOtherText.trim() : undefined,
      task_type: taskType,
      priority,
      assignee_id: assigneeId || null,
    });
    setSubmitting(false);
    if (created) resetAndClose();
  };

  // Keep the panel mounted through its closing transition instead of
  // unmounting immediately on `open = false`, so the slide-out is visible
  // rather than the panel just vanishing.
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        type="button"
        aria-label="Close new task panel"
        onClick={resetAndClose}
        className="absolute inset-0 bg-ink/30 backdrop-blur-[2px] animate-[fade-in_0.15s_ease-out]"
      />
      <div className="relative flex h-full w-full max-w-[480px] flex-col overflow-y-auto bg-canvas shadow-2xl shadow-ink/25 animate-[slide-in_0.22s_cubic-bezier(0.16,1,0.3,1)]">
        <div className="flex items-start justify-between gap-4 border-b border-canvas-soft px-6 py-5">
          <div>
            <h2 className="text-lg font-bold tracking-tight text-ink">New task</h2>
            <p className="mt-1 text-xs text-mute">
              Employees mostly create and start their own tasks — assignee defaults to you.
            </p>
          </div>
          <button
            type="button"
            onClick={resetAndClose}
            className="shrink-0 rounded-full p-1.5 text-mute hover:bg-canvas-soft hover:text-ink"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 p-6">
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
              {TASK_CATEGORIES.map((c) => (
                <option key={c.key} value={c.key}>
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
                <option value="normal">Normal</option>
                <option value="expedite">Expedite</option>
              </Select>
            </label>
          </div>

          <label className="space-y-1.5 text-sm">
            <span className="font-semibold text-ink">Assignee</span>
            <Select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}>
              {board.users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.id === board.currentUserId ? `${u.full_name} (me)` : u.full_name}
                </option>
              ))}
            </Select>
          </label>

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

          <div className="mt-auto flex gap-2 border-t border-canvas-soft pt-4">
            <Button variant="primary" type="submit" disabled={!title.trim() || submitting} className="flex-1">
              {submitting ? "Creating…" : "Create task"}
            </Button>
            <Button variant="tertiary" type="button" onClick={resetAndClose}>
              Cancel
            </Button>
          </div>
        </form>
      </div>
      <style jsx global>{`
        @keyframes slide-in {
          from {
            transform: translateX(24px);
            opacity: 0;
          }
          to {
            transform: translateX(0);
            opacity: 1;
          }
        }
        @keyframes fade-in {
          from {
            opacity: 0;
          }
          to {
            opacity: 1;
          }
        }
      `}</style>
    </div>
  );
}
