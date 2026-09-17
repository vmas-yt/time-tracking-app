"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { BoardProvider } from "@/board/store";
import { BoardScreen } from "./BoardScreen";

// The Kanban board — 5 fixed columns (Backlog/To Do/In Progress/On Hold/
// Completed), swim lanes grouped by whatever field the admin picked
// (assignee/task type/category/priority), backed by the real API via
// `BoardProvider` (see src/board/store.tsx). Task creation, drag-and-drop
// status moves, and the timer widget all call the FastAPI backend directly
// — no dummy data or client-side state machine simulating the backend.
// `?project=<id>` (linked from the project list on `/`) scopes the board to
// one project; tasks are standalone by default per the PRD.
function BoardWithProject() {
  const params = useSearchParams();
  const projectId = params.get("project");
  return (
    <BoardProvider projectId={projectId}>
      <BoardScreen />
    </BoardProvider>
  );
}

export default function BoardPage() {
  return (
    <main className="mx-auto max-w-[1700px] px-6 py-8">
      <Suspense fallback={<p className="text-sm text-mute">Loading…</p>}>
        <BoardWithProject />
      </Suspense>
    </main>
  );
}
