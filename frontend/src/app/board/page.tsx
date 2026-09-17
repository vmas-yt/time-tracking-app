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
    <main className="mx-auto max-w-[1600px] px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-ink">Board</h1>
        <p className="mt-1 text-sm text-mute">
          Tasks are standalone by default — link one to a project from its detail page if needed.
        </p>
      </div>
      <Suspense fallback={<p className="text-sm text-mute">Loading…</p>}>
        <BoardContent />
      </Suspense>
    </main>
  );
}
