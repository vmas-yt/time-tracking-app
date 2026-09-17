"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import type { TaskCategory, TaskPriority, TaskType } from "@/lib/types";
import { TASK_CATEGORIES } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Input";
import { useBoard } from "@/board/store";

/** Inline task-creation form. The PRD's primary flow is "employees mostly
 * create and start their own tasks without needing a project" — so this
 * defaults assignee to "myself" and doesn't require a project link. */
export function NewTaskForm({ onDone }: { onDone: () => void }) {
  const board = useBoard();
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<TaskCategory>("meeting");
  const [categoryOtherText, setCategoryOtherText] = useState("");
  const [taskType, setTaskType] = useState<TaskType>("normal");
  const [priority, setPriority] = useState<TaskPriority>("normal");
  const [assigneeId, setAssigneeId] = useState<string>(board.currentUserId);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

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
    if (created) onDone();
  };

  return (
    <Card className="p-4">
      <form onSubmit={handleSubmit} className="flex flex-wrap items-start gap-2">
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Task title"
          className="max-w-xs"
          autoFocus
        />
        <Select value={category} onChange={(e) => setCategory(e.target.value as TaskCategory)} className="w-auto">
          {TASK_CATEGORIES.map((c) => (
            <option key={c.key} value={c.key}>
              {c.label}
            </option>
          ))}
        </Select>
        {category === "other" && (
          <Input
            value={categoryOtherText}
            onChange={(e) => setCategoryOtherText(e.target.value)}
            placeholder="Describe category"
            className="max-w-[160px]"
          />
        )}
        <Select value={taskType} onChange={(e) => setTaskType(e.target.value as TaskType)} className="w-auto">
          <option value="normal">Normal</option>
          <option value="ad_hoc">Ad-hoc</option>
        </Select>
        <Select value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)} className="w-auto">
          <option value="normal">Normal priority</option>
          <option value="expedite">Expedite</option>
        </Select>
        <Select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)} className="w-auto">
          {board.users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.id === board.currentUserId ? `${u.full_name} (me)` : u.full_name}
            </option>
          ))}
        </Select>
        <Input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description (optional)"
          className="min-w-[200px] flex-1"
        />
        <div className="flex gap-2">
          <Button variant="primary" type="submit" disabled={!title.trim() || submitting}>
            {submitting ? "Creating…" : "Create task"}
          </Button>
          <Button variant="tertiary" type="button" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}
