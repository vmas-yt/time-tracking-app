"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { AuditEntry, Comment, TaskCategory, TaskPriority } from "@/lib/types";
import { TASK_PRIORITIES } from "@/lib/types";
import { Badge, ManualEntryBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input, Select } from "@/components/ui/Input";
import { SlideOver, SlideOverHeader } from "@/components/ui/SlideOver";
import { useBoard } from "@/board/store";
import { formatRelativeTime } from "@/board/format";
import { activeOptions, categoryLabelFor } from "@/lib/options";
import { CustomFieldInput } from "./CustomFieldInput";
import { TimerControls } from "./TimerControls";

const STATUS_TONE = {
  backlog: "gray",
  todo: "blue",
  in_progress: "brand",
  on_hold: "amber",
  completed: "green",
} as const;

export function TaskDetailPanel() {
  const board = useBoard();
  const task = board.tasks.find((t) => t.id === board.selectedTaskId) ?? null;

  const [comments, setComments] = useState<Comment[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);

  // ---- Edit mode (docs/design/custom-fields-admin-design.md §0) ----------
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editCategory, setEditCategory] = useState<TaskCategory>("");
  const [editCategoryOtherText, setEditCategoryOtherText] = useState("");
  const [editPriority, setEditPriority] = useState<TaskPriority>("normal");
  const [editAssigneeId, setEditAssigneeId] = useState("");
  const [editProjectId, setEditProjectId] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // ---- Delete / archive (§5.3) --------------------------------------------
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [offerArchive, setOfferArchive] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  // ---- Custom fields, per-field save feedback -----------------------------
  // Local drafts, keyed by field id, so a controlled input can be typed into
  // without waiting on a round-trip PATCH + board refresh for every
  // keystroke — only re-seeded when the *selected task* changes, not on
  // every background task-list refresh (which would otherwise wipe an
  // in-progress edit on one field the moment another field's commit
  // refreshes the list).
  const [customDrafts, setCustomDrafts] = useState<Record<string, string>>({});
  const [customFieldError, setCustomFieldError] = useState<string | null>(null);
  const [savingFieldId, setSavingFieldId] = useState<string | null>(null);

  const loadActivity = async (taskId: string) => {
    setActivityLoading(true);
    setActivityError(null);
    try {
      const [c, a] = await Promise.all([api.listComments(taskId), api.listAudit(taskId)]);
      setComments(c);
      setAudit(a);
    } catch (err) {
      setActivityError(err instanceof Error ? err.message : "Could not load comments/audit trail");
    } finally {
      setActivityLoading(false);
    }
  };

  useEffect(() => {
    if (!task) return;
    loadActivity(task.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id]);

  // Reset all per-task transient UI state (edit mode, delete confirmation,
  // etc.) whenever the selection changes, so switching from task A to task B
  // never carries over an in-progress edit or a pending confirm dialog.
  useEffect(() => {
    setEditing(false);
    setConfirmingDelete(false);
    setOfferArchive(false);
    setDeleteError(null);
    setCustomFieldError(null);
    setCustomDrafts(task?.custom_values ?? {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (editing) setEditing(false);
        else board.selectTask(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id, editing]);

  if (!task) return null;

  const assignee = board.users.find((u) => u.id === task.assignee_id);
  const creator = board.users.find((u) => u.id === task.created_by_id);
  const categoryLabel = categoryLabelFor(task, board.categoryOptions);
  const canEdit = board.canEditTask(task);
  const isAdmin = board.currentUser?.role === "admin";
  const authorName = (id: string) =>
    id === board.currentUserId ? "You" : board.users.find((u) => u.id === id)?.full_name ?? id;

  const categoryChoices = activeOptions(board.categoryOptions);
  const priorityChoices = board.priorityOptions.length
    ? activeOptions(board.priorityOptions)
    : TASK_PRIORITIES.map((p) => ({ value: p.key, label: p.label }));

  const beginEdit = () => {
    setEditTitle(task.title);
    setEditDescription(task.description ?? "");
    setEditCategory(task.category);
    setEditCategoryOtherText(task.category_other_text ?? "");
    setEditPriority(task.priority);
    setEditAssigneeId(task.assignee_id ?? "");
    setEditProjectId(task.project_id ?? "");
    setEditError(null);
    setEditing(true);
  };

  const handleSaveEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editTitle.trim()) return;
    if (editCategory === "other" && !editCategoryOtherText.trim()) return;
    setSavingEdit(true);
    setEditError(null);
    const updated = await board.updateTask(task.id, {
      title: editTitle.trim(),
      description: editDescription.trim(),
      category: editCategory,
      category_other_text: editCategory === "other" ? editCategoryOtherText.trim() : undefined,
      priority: editPriority,
      assignee_id: editAssigneeId || null,
      project_id: editProjectId || null,
    });
    setSavingEdit(false);
    if (updated) setEditing(false);
    else setEditError("Could not save changes — see the toast for details.");
  };

  const handleCustomFieldCommit = async (fieldId: string, value: string) => {
    if ((task.custom_values[fieldId] ?? "") === value) return; // no-op, nothing changed
    setSavingFieldId(fieldId);
    setCustomFieldError(null);
    try {
      await api.updateTask(task.id, { custom_values: { [fieldId]: value } });
      board.refresh();
    } catch (err) {
      setCustomFieldError(errorMessage(err));
      // Revert the draft to the last-known-good server value on failure so
      // the input doesn't keep showing a value that was actually rejected.
      setCustomDrafts((prev) => ({ ...prev, [fieldId]: task.custom_values[fieldId] ?? "" }));
    } finally {
      setSavingFieldId(null);
    }
  };

  const handleComment = async (e: FormEvent) => {
    e.preventDefault();
    const body = draft.trim();
    if (!body) return;
    setPosting(true);
    try {
      await api.addComment(task.id, body);
      setDraft("");
      await loadActivity(task.id);
    } catch (err) {
      setActivityError(err instanceof Error ? err.message : "Could not post comment");
    } finally {
      setPosting(false);
    }
  };

  const handleDelete = async () => {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.deleteTask(task.id);
      setConfirmingDelete(false);
      board.selectTask(null);
      board.refresh();
    } catch (err) {
      setConfirmingDelete(false);
      if (err instanceof ApiError && err.status === 409) {
        if (isAdmin) {
          setOfferArchive(true);
        } else {
          setDeleteError(err.message);
        }
      } else {
        setDeleteError(errorMessage(err));
      }
    } finally {
      setDeleteBusy(false);
    }
  };

  const handleArchive = async () => {
    setDeleteBusy(true);
    try {
      await api.archiveTask(task.id);
      setOfferArchive(false);
      board.selectTask(null);
      board.refresh();
    } catch (err) {
      setOfferArchive(false);
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <>
    <SlideOver
      open
      onClose={() => board.selectTask(null)}
      widthClassName="max-w-[520px]"
      closeLabel="Close task details"
      disableEscapeClose
    >
      <SlideOverHeader onClose={() => board.selectTask(null)}>
        {editing ? (
          <div className="w-full space-y-1">
            <span className="text-xs font-semibold uppercase tracking-wide text-mute">Editing task</span>
            <h2 className="text-lg font-bold leading-tight tracking-tight text-ink">{task.title}</h2>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={STATUS_TONE[task.status]}>{task.status.replace("_", " ")}</Badge>
              {task.is_manual_entry && <ManualEntryBadge />}
              {task.task_type === "ad_hoc" && <Badge tone="amber">Ad-hoc</Badge>}
              {task.priority === "expedite" && <Badge tone="red">Expedite</Badge>}
              <Badge tone="blue">{categoryLabel}</Badge>
              {task.archived_at && <Badge tone="gray">Archived</Badge>}
            </div>
            <h2 className="text-xl font-bold leading-tight tracking-tight text-ink">{task.title}</h2>
            <p className="text-xs text-mute">
              Assigned to <span className="font-semibold text-body">{assignee?.full_name ?? "Unassigned"}</span>
              {creator && creator.id !== assignee?.id && <> · created by {creator.full_name}</>}
            </p>
          </div>
        )}
      </SlideOverHeader>

        <div className="space-y-5 p-6">
          {!editing && canEdit && (
            <div className="flex justify-end">
              <Button size="sm" variant="secondary" onClick={beginEdit}>
                Edit task
              </Button>
            </div>
          )}

          {editing ? (
            <Card className="p-4">
              <form onSubmit={handleSaveEdit} className="space-y-4">
                {editError && <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{editError}</p>}
                <label className="block space-y-1.5 text-sm">
                  <span className="font-semibold text-ink">Title</span>
                  <Input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} autoFocus />
                </label>
                <label className="block space-y-1.5 text-sm">
                  <span className="font-semibold text-ink">Category</span>
                  <Select value={editCategory} onChange={(e) => setEditCategory(e.target.value)}>
                    {categoryChoices.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </Select>
                </label>
                {editCategory === "other" && (
                  <label className="block space-y-1.5 text-sm">
                    <span className="font-semibold text-ink">Describe category</span>
                    <Input
                      value={editCategoryOtherText}
                      onChange={(e) => setEditCategoryOtherText(e.target.value)}
                    />
                  </label>
                )}
                <label className="block space-y-1.5 text-sm">
                  <span className="font-semibold text-ink">Priority</span>
                  <Select value={editPriority} onChange={(e) => setEditPriority(e.target.value)}>
                    {priorityChoices.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </Select>
                </label>
                <p className="text-xs text-mute">
                  Task type (Normal/Ad-hoc) is set at creation and can&rsquo;t be changed here.
                </p>
                <label className="block space-y-1.5 text-sm">
                  <span className="font-semibold text-ink">Assignee</span>
                  <Select value={editAssigneeId} onChange={(e) => setEditAssigneeId(e.target.value)}>
                    <option value="">Unassigned</option>
                    {board.users.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.full_name}
                      </option>
                    ))}
                  </Select>
                </label>
                <label className="block space-y-1.5 text-sm">
                  <span className="font-semibold text-ink">Project</span>
                  <Select value={editProjectId} onChange={(e) => setEditProjectId(e.target.value)}>
                    <option value="">No project (standalone)</option>
                    {board.projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </Select>
                </label>
                <label className="block space-y-1.5 text-sm">
                  <span className="font-semibold text-ink">Description</span>
                  <textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    rows={4}
                    className="w-full rounded-md border border-ink bg-canvas px-4 py-2.5 text-sm text-ink placeholder:text-mute focus:outline-none focus:ring-2 focus:ring-primary-neutral"
                  />
                </label>
                <div className="flex gap-2 border-t border-canvas-soft pt-4">
                  <Button variant="primary" type="submit" disabled={!editTitle.trim() || savingEdit}>
                    {savingEdit ? "Saving…" : "Save changes"}
                  </Button>
                  <Button variant="tertiary" type="button" onClick={() => setEditing(false)} disabled={savingEdit}>
                    Cancel
                  </Button>
                </div>
              </form>
            </Card>
          ) : (
            <Card className="p-4">
              {task.description && <p className="mb-3 text-sm leading-relaxed text-body">{task.description}</p>}

              <div className="mb-3 grid grid-cols-2 gap-4 border-b border-canvas-soft pb-3 text-xs">
                <div>
                  <div className="font-semibold text-ink">Start date</div>
                  {task.started_at ? (
                    <div className="text-body">{new Date(task.started_at).toLocaleDateString()}</div>
                  ) : (
                    <div className="italic text-mute">Not started yet</div>
                  )}
                </div>
                <div>
                  <div className="font-semibold text-ink">Completion date</div>
                  {task.completed_at ? (
                    <div className="text-body">{new Date(task.completed_at).toLocaleDateString()}</div>
                  ) : (
                    <div className="italic text-mute">Not completed yet</div>
                  )}
                </div>
              </div>

              <TimerControls
                task={task}
                entries={board.entries}
                currentUserId={board.currentUserId}
                canEdit={board.canEditTask(task)}
                isPending={board.isPending(task.id)}
                onStart={board.start}
                onPause={board.pause}
                onResume={board.resume}
                onStop={board.stop}
                onManualLog={async (taskId, input) => {
                  const result = await board.logManualTime(taskId, input);
                  return result !== null;
                }}
                size="md"
              />
            </Card>
          )}

          {board.customFields.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Custom fields</CardTitle>
              </CardHeader>
              <CardBody className="space-y-4">
                {customFieldError && (
                  <p className="rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{customFieldError}</p>
                )}
                {board.customFields.map((field) => (
                  <div key={field.id} className="grid grid-cols-[1fr_1.4fr] items-center gap-3 text-sm">
                    <span className="font-semibold text-ink">{field.name}</span>
                    {canEdit ? (
                      <div className="flex items-center gap-2">
                        <div className="flex-1">
                          <CustomFieldInput
                            field={field}
                            value={customDrafts[field.id] ?? ""}
                            onChange={(value) => setCustomDrafts((prev) => ({ ...prev, [field.id]: value }))}
                            onCommit={(value) => handleCustomFieldCommit(field.id, value)}
                          />
                        </div>
                        {savingFieldId === field.id && <span className="text-xs text-mute">Saving…</span>}
                      </div>
                    ) : (
                      <span className="text-body">{task.custom_values[field.id] || "—"}</span>
                    )}
                  </div>
                ))}
              </CardBody>
            </Card>
          )}

          {activityError && (
            <p className="rounded-xl bg-negative-bg px-4 py-2 text-sm text-canvas">{activityError}</p>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Comments</CardTitle>
            </CardHeader>
            <CardBody className="space-y-4">
              <form onSubmit={handleComment} className="flex gap-2">
                <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Add a comment…" />
                <Button variant="primary" type="submit" disabled={!draft.trim() || posting}>
                  Post
                </Button>
              </form>
              {activityLoading ? (
                <p className="text-sm text-mute">Loading…</p>
              ) : comments.length === 0 ? (
                <p className="text-sm text-mute">No comments yet — be the first to add context.</p>
              ) : (
                <ul className="space-y-3">
                  {comments.map((c) => (
                    <li key={c.id} className="border-t border-canvas-soft pt-3 text-sm first:border-0 first:pt-0">
                      <span className="font-semibold text-ink">{authorName(c.author_id)}</span>{" "}
                      <span className="text-body">{c.body}</span>
                      <div className="mt-0.5 text-xs text-mute">{formatRelativeTime(c.created_at)}</div>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Audit trail</CardTitle>
            </CardHeader>
            <CardBody>
              {activityLoading ? (
                <p className="text-sm text-mute">Loading…</p>
              ) : audit.length === 0 ? (
                <p className="text-sm text-mute">No activity yet.</p>
              ) : (
                <ol className="space-y-3 border-l border-canvas-soft pl-4">
                  {audit.map((a) => (
                    <li key={a.id} className="relative text-xs">
                      <span className="absolute -left-[21px] top-1 h-2 w-2 rounded-full bg-primary-neutral" />
                      <span className="font-semibold text-body">{authorName(a.actor_id)}</span>{" "}
                      <span className="text-mute">{a.action.replace(/_/g, " ")}</span>
                      <div className="text-mute">{a.detail}</div>
                      <div className="mt-0.5 text-[11px] text-mute/70">{formatRelativeTime(a.created_at)}</div>
                    </li>
                  ))}
                </ol>
              )}
            </CardBody>
          </Card>

          {canEdit && (
            <div className="rounded-xl bg-negative-bg/[0.08] p-4">
              {deleteError && (
                <p className="mb-3 rounded-xl bg-negative-bg px-3 py-2 text-xs text-canvas">{deleteError}</p>
              )}
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-ink">Delete this task</p>
                  <p className="text-xs text-mute">
                    Permanent, and only possible if no time has been logged against it yet.
                  </p>
                </div>
                <Button variant="danger" size="sm" onClick={() => setConfirmingDelete(true)}>
                  Delete task
                </Button>
              </div>
            </div>
          )}
        </div>
    </SlideOver>

      <ConfirmDialog
        open={confirmingDelete}
        title="Delete this task?"
        description="This can't be undone. If time has already been logged against it, deleting will fail instead of erasing that history."
        confirmLabel="Delete"
        tone="danger"
        busy={deleteBusy}
        onConfirm={handleDelete}
        onCancel={() => setConfirmingDelete(false)}
      />

      <ConfirmDialog
        open={offerArchive}
        title="Archive this task instead?"
        description="This task has logged time and can't be deleted. Archiving hides it from the board and reports while keeping its full history."
        confirmLabel="Archive"
        busy={deleteBusy}
        onConfirm={handleArchive}
        onCancel={() => setOfferArchive(false)}
      />
    </>
  );
}
