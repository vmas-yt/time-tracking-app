import { PrototypeBoardProvider } from "@/prototype/board/store";
import { BoardScreen } from "./BoardScreen";

// Isolated, dummy-data prototype of the Kanban board + timer feature for
// design approval. No lib/api.ts usage anywhere in this route — everything
// lives in in-memory React state seeded from @/prototype/board/seed and
// driven by the state machine in @/prototype/board/engine. Does not touch
// the real /board route or its components.
export default function PrototypeBoardPage() {
  return (
    <main className="mx-auto max-w-[1700px] px-6 py-8">
      <PrototypeBoardProvider>
        <BoardScreen />
      </PrototypeBoardProvider>
    </main>
  );
}
