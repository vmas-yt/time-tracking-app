# Frontend (Next.js)

## Setup

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Runs at `http://localhost:3000`. Requires the backend running at the URL in
`NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).

## Structure

- `src/app/` — routes: `/` (project list), `/login`, `/board?project=<id>`
  (Kanban board), `/admin` (user list).
- `src/components/` — `KanbanBoard`, `SwimLane` (grouped by assignee),
  `TaskCard`, `TimerControls`.
- `src/lib/api.ts` — thin fetch wrapper against the FastAPI backend, JWT
  stored in `localStorage`.

The Kanban board groups tasks into swim lanes by assignee, with columns for
each task status (`backlog`, `todo`, `in_progress`, `in_review`, `done`).
Drag a card to a new column to change its status. Each task card has inline
timer controls reflecting the backend's timer state machine — only one
timer can be active per user at a time, and controls only offer actions
valid for the entry's current state.

## Known follow-up

`npm audit` reports moderate/high advisories in `postcss`, a build-time
transitive dependency of Next.js with no runtime exposure in this app.
Clearing them requires the Next.js 16 major upgrade (React 19); left for a
deliberate follow-up rather than bundled into this scaffold.
