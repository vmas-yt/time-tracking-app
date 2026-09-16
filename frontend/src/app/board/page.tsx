"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { KanbanBoard } from "@/components/KanbanBoard";

function BoardContent() {
  const params = useSearchParams();
  const projectId = params.get("project") ?? undefined;

  return <KanbanBoard projectId={projectId} />;
}

export default function BoardPage() {
  return (
    <main className="page">
      <h1>Board</h1>
      <p className="board-hint">
        Tasks are standalone by default — link one to a project from its detail page if you need to.
      </p>
      <Suspense fallback={<p>Loading…</p>}>
        <BoardContent />
      </Suspense>
    </main>
  );
}
