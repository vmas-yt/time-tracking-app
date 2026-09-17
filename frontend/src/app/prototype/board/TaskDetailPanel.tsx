"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { TASK_CATEGORIES } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { formatRelativeTime } from "@/prototype/board/format";
import { usePrototypeBoard } from "@/prototype/board/store";
import { TimerControls } from "./TimerControls";

const STATUS_TONE = {
  backlog: "gray",
  todo: "blue",
  in_progress: "brand",
  on_hold: "amber",
  completed: "green",
} as const;

export function TaskDetailPanel() {
  const board = usePrototypeBoard();
  const [draft, setDraft] = useState("");
  const task = board.tasks.find((t) => t.id === board.selectedTaskId) ?? null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") board.selectTask(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id]);

  if (!task) return null;

  const assignee = board.users.find((u) => u.id === task.assignee_id);
  const creator = board.users.find((u) => u.id === task.created_by_id);
  const categoryLabel =
    TASK_CATEGORIES.find((c) => c.key === task.category)?.label ?? task.category_other_text ?? task.category;
  const comments = board.comments.filter((c) => c.task_id === task.id);
  const audit = board.audit
    .filter((a) => a.task_id === task.id)
    .slice()
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  const authorName = (id: string) => (id === board.currentUserId ? "You" : board.users.find((u) => u.id === id)?.full_name ?? id);

  const handleComment = (e: FormEvent) => {
    e.preventDefault();
    if (!draft.trim()) return;
    board.comment(task.id, draft.trim());
    setDraft("");
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        type="button"
        aria-label="Close task details"
        onClick={() => board.selectTask(null)}
        className="absolute inset-0 bg-ink/30 backdrop-blur-[2px] animate-[fade-in_0.15s_ease-out]"
      />
      <div className="relative flex h-full w-full max-w-[520px] flex-col overflow-y-auto bg-canvas-soft shadow-2xl shadow-ink/25 animate-[slide-in_0.22s_cubic-bezier(0.16,1,0.3,1)]">
        <div className="flex items-start justify-between gap-4 border-b border-canvas px-6 py-5">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={STATUS_TONE[task.status]}>{task.status.replace("_", " ")}</Badge>
              {task.task_type === "ad_hoc" && <Badge tone="amber">Ad-hoc</Badge>}
              {task.priority === "expedite" && <Badge tone="red">Expedite</Badge>}
              <Badge tone="blue">{categoryLabel}</Badge>
            </div>
            <h2 className="text-xl font-bold leading-tight tracking-tight text-ink">{task.title}</h2>
            <p className="text-xs text-mute">
              Assigned to <span className="font-semibold text-body">{assignee?.full_name ?? "Unassigned"}</span>
              {creator && creator.id !== assignee?.id && <> · created by {creator.full_name}</>}
            </p>
          </div>
          <button
            type="button"
            onClick={() => board.selectTask(null)}
            className="shrink-0 rounded-full p-1.5 text-mute hover:bg-canvas hover:text-ink"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="space-y-5 p-6">
          <Card className="p-4">
            {task.description && <p className="mb-3 text-sm leading-relaxed text-body">{task.description}</p>}
            <TimerControls task={task} size="md" />
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Comments</CardTitle>
            </CardHeader>
            <CardBody className="space-y-4">
              <form onSubmit={handleComment} className="flex gap-2">
                <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Add a comment…" />
                <Button variant="primary" type="submit" disabled={!draft.trim()}>
                  Post
                </Button>
              </form>
              {comments.length === 0 ? (
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
              {audit.length === 0 ? (
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
        </div>
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
