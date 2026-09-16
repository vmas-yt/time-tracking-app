"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

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
    <main className="page">
      <h1>Projects</h1>
      {error && <p style={{ color: "var(--accent-danger)" }}>{error} — log in first at /login</p>}
      <form onSubmit={handleCreate} style={{ marginBottom: 24, display: "flex", gap: 8 }}>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New project name"
          style={{ padding: 8, borderRadius: 6, border: "1px solid var(--border)" }}
        />
        <button className="timer-btn timer-btn--start" type="submit">
          Create
        </button>
      </form>
      <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        {projects.map((p) => (
          <li key={p.id}>
            <Link href={`/board?project=${p.id}`} style={{ color: "var(--accent)" }}>
              {p.name}
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
