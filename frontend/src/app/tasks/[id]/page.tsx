"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AuditEntry, Comment, Task, User } from "@/lib/types";
import { categoryLabelFor } from "@/lib/options";
import { useTimerSession } from "@/board/session";
import { TimerControls } from "@/app/board/TimerControls";
import { Toast } from "@/app/board/Toast";
import { Badge, ManualEntryBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

export default function TaskDetailPage() {
  const params = useParams<{ id: string }>();
  const taskId = params.id;

  const [task, setTask] = useState<Task | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [newComment, setNewComment] = useState("");
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTask = useCallback(() => {
    api.getTask(taskId).then(setTask).catch((e) => setError(e.message));
  }, [taskId]);

  const session = useTimerSession({ onMutated: loadTask });

  const load = useCallback(() => {
    loadTask();
    api.listComments(taskId).then(setComments).catch(console.error);
    api.listAudit(taskId).then(setAudit).catch(console.error);
    api.listUsers({ includeInactive: true }).then(setUsers).catch(console.error);
  }, [taskId, loadTask]);

  useEffect(load, [load]);

  const handleComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newComment.trim()) return;
    setPosting(true);
    try {
      await api.addComment(taskId, newComment.trim());
      setNewComment("");
      await Promise.all([api.listComments(taskId).then(setComments), api.listAudit(taskId).then(setAudit)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not post comment");
    } finally {
      setPosting(false);
    }
  };

  const authorName = (id: string) =>
    id === session.currentUser?.id ? "You" : users.find((u) => u.id === id)?.full_name ?? id;

  if (error)
    return (
      <main className="mx-auto max-w-3xl px-6 py-10">
        <p className="text-sm text-negative">{error}</p>
      </main>
    );
  if (!task)
    return (
      <main className="mx-auto max-w-3xl px-6 py-10">
        <p className="text-sm text-mute">Loading…</p>
      </main>
    );

  const categoryLabel = categoryLabelFor(task, []);

  return (
    <main className="mx-auto max-w-5xl px-6 py-8">
      <Link href="/board" className="text-sm text-mute hover:text-body">
        ← Back to board
      </Link>

      <div className="mt-3 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-ink">{task.title}</h1>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge tone="brand">{task.status.replace("_", " ")}</Badge>
              {task.is_manual_entry && <ManualEntryBadge />}
              <Badge tone="blue">{categoryLabel}</Badge>
              <Badge tone="gray">{task.task_type === "ad_hoc" ? "Ad-hoc" : "Normal"}</Badge>
              {task.priority === "expedite" && <Badge tone="red">Expedite</Badge>}
            </div>
            {task.description && <p className="mt-4 text-sm text-body">{task.description}</p>}

            <div className="mt-4 grid grid-cols-2 gap-4 border-b border-canvas-soft pb-4 text-xs">
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

            <div className="mt-4">
              <TimerControls
                task={task}
                entries={session.entries}
                currentUserId={session.currentUser?.id ?? ""}
                canEdit={session.canEditTask(task)}
                isPending={session.isPending(task.id)}
                onStart={session.start}
                onPause={session.pause}
                onResume={session.resume}
                onStop={session.stop}
                onManualLog={async (taskId, input) => {
                  const result = await session.runMutation(taskId, () => api.logManualTimeForTask(taskId, input));
                  return result !== null;
                }}
                size="md"
              />
            </div>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Comments</CardTitle>
            </CardHeader>
            <CardBody className="space-y-4">
              <form onSubmit={handleComment} className="flex gap-2">
                <Input
                  value={newComment}
                  onChange={(e) => setNewComment(e.target.value)}
                  placeholder="Add a comment"
                />
                <Button variant="primary" type="submit" disabled={!newComment.trim() || posting}>
                  Post
                </Button>
              </form>
              {comments.length === 0 ? (
                <p className="text-sm text-mute">No comments yet.</p>
              ) : (
                <ul className="space-y-3">
                  {comments.map((c) => (
                    <li key={c.id} className="border-t border-canvas-soft pt-3 text-sm first:border-0 first:pt-0">
                      <span className="font-semibold text-ink">{authorName(c.author_id)}</span>{" "}
                      <span className="text-body">{c.body}</span>
                      <div className="mt-0.5 text-xs text-mute">
                        {new Date(c.created_at).toLocaleString()}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>

        <Card className="h-fit bg-canvas-soft">
          <CardHeader>
            <CardTitle>Audit trail</CardTitle>
          </CardHeader>
          <CardBody>
            {audit.length === 0 ? (
              <p className="text-sm text-mute">No activity yet.</p>
            ) : (
              <ul className="space-y-3">
                {audit.map((a) => (
                  <li key={a.id} className="text-xs">
                    <span className="font-semibold text-body">{authorName(a.actor_id)}</span>{" "}
                    <span className="text-mute">{a.action.replace(/_/g, " ")}</span>
                    <div className="text-mute">{a.detail}</div>
                    <div className="mt-0.5 text-[11px] text-mute/70">
                      {new Date(a.created_at).toLocaleString()}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>
      <Toast toast={session.toast} dismissToast={session.dismissToast} />
    </main>
  );
}
