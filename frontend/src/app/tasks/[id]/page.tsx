"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { TASK_CATEGORIES } from "@/lib/types";
import type { AuditEntry, Comment, Task, TimeEntry, User } from "@/lib/types";
import { TimerControls } from "@/components/TimerControls";

export default function TaskDetailPage() {
  const params = useParams<{ id: string }>();
  const taskId = params.id;

  const [task, setTask] = useState<Task | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [openEntries, setOpenEntries] = useState<TimeEntry[]>([]);
  const [newComment, setNewComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.getTask(taskId).then(setTask).catch((e) => setError(e.message));
    api.listComments(taskId).then(setComments).catch(console.error);
    api.listAudit(taskId).then(setAudit).catch(console.error);
    api.listUsers().then(setUsers).catch(console.error);
    api.listOpenTimers().then(setOpenEntries).catch(console.error);
  };

  useEffect(load, [taskId]);

  const handleComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newComment.trim()) return;
    await api.addComment(taskId, newComment.trim());
    setNewComment("");
    load();
  };

  const authorName = (id: string) => users.find((u) => u.id === id)?.full_name ?? id;

  if (error) return <main className="page"><p>{error}</p></main>;
  if (!task) return <main className="page"><p>Loading…</p></main>;

  const categoryLabel =
    TASK_CATEGORIES.find((c) => c.key === task.category)?.label ?? task.category_other_text ?? task.category;

  return (
    <main className="page task-detail">
      <Link href="/">&larr; Back to projects</Link>
      <h1>{task.title}</h1>
      <div className="task-detail__meta">
        <span className="badge badge--category">{categoryLabel}</span>
        <span className="badge">{task.task_type === "ad_hoc" ? "Ad-hoc" : "Normal"}</span>
        {task.priority === "expedite" && <span className="badge badge--expedite">Expedite</span>}
        <span className="badge">{task.status}</span>
      </div>
      {task.description && <p>{task.description}</p>}
      <TimerControls task={task} openEntries={openEntries} onChange={load} />

      <section>
        <h2>Comments</h2>
        <form onSubmit={handleComment} className="task-detail__comment-form">
          <input
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
            placeholder="Add a comment"
          />
          <button className="timer-btn timer-btn--start" type="submit">
            Post
          </button>
        </form>
        <ul className="task-detail__list">
          {comments.map((c) => (
            <li key={c.id}>
              <strong>{authorName(c.author_id)}</strong> — {c.body}
              <span className="task-detail__timestamp">{new Date(c.created_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Audit trail</h2>
        <ul className="task-detail__list">
          {audit.map((a) => (
            <li key={a.id}>
              <strong>{authorName(a.actor_id)}</strong> {a.action} — {a.detail}
              <span className="task-detail__timestamp">{new Date(a.created_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
