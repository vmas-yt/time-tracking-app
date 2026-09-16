"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { KanbanBoard } from "@/components/KanbanBoard";

function BoardContent() {
  const params = useSearchParams();
  const projectId = params.get("project");

  if (!projectId) {
    return <p>Pick a project from the home page to see its board.</p>;
  }

  return <KanbanBoard projectId={projectId} />;
}

export default function BoardPage() {
  return (
    <main className="page">
      <h1>Board</h1>
      <Suspense fallback={<p>Loading…</p>}>
        <BoardContent />
      </Suspense>
    </main>
  );
}
