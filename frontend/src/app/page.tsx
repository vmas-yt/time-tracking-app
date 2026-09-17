"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

export default function HomePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const loadProjects = () => api.listProjects().then(setProjects).catch((e) => setError(e.message));

  useEffect(() => {
    loadProjects();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    await api.createProject(name.trim());
    setName("");
    loadProjects();
  };

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink">Projects</h1>
          <p className="mt-1 text-sm text-mute">
            Optional groupings for tasks — most work happens directly on the{" "}
            <Link href="/board" className="font-semibold text-ink-deep hover:underline">
              board
            </Link>
            .
          </p>
        </div>
      </div>

      {error && (
        <p className="mb-6 rounded-xl bg-negative-bg px-4 py-3 text-sm text-canvas">
          {error} — log in first at{" "}
          <Link href="/login" className="underline">
            /login
          </Link>
        </p>
      )}

      <form onSubmit={handleCreate} className="mb-6 flex gap-2">
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New project name"
          className="max-w-xs"
        />
        <Button variant="primary" type="submit">
          Create
        </Button>
      </form>

      {projects.length === 0 ? (
        <Card className="px-6 py-12 text-center text-sm text-mute">No projects yet.</Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <Link key={p.id} href={`/board?project=${p.id}`}>
              <Card className="h-full px-5 py-4 transition-colors hover:bg-primary-pale">
                <div className="font-bold text-ink">{p.name}</div>
                {p.description && (
                  <div className="mt-1 line-clamp-2 text-sm text-body">{p.description}</div>
                )}
              </Card>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
