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

- `src/app/` — routes:
  - `/` — project list
  - `/login` — register/log in
  - `/board?project=<id>` — Kanban board (project filter optional; tasks
    are standalone by default per the PRD)
  - `/tasks/[id]` — task detail: description, timer, comments, audit trail
  - `/admin` — swim-lane grouping, custom fields, user role/manager
    assignment
  - `/reports` — control chart, cycle time, lead time, throughput,
    cumulative flow diagram
- `src/components/` — `KanbanBoard`, `SwimLane` (grouping is
  admin-configurable — see `BoardConfig`), `TaskCard`, `TimerControls`,
  `NavBar`.
- `src/components/ui/` — the design system's primitives (`Button`, `Card`,
  `Badge`, `Input`, `Select`). Build new UI out of these rather than
  hand-rolling styles, so the app stays visually consistent.
- `src/lib/api.ts` — thin fetch wrapper against the FastAPI backend, JWT
  stored in `localStorage`.
- `src/lib/types.ts` — mirrors the backend's Pydantic schemas.

The Kanban board has 5 fixed columns (`backlog`, `todo`, `in_progress`,
`on_hold`, `completed`) and swim lanes grouped by whatever field the admin
picked (team member, task type, category, or priority). Dragging a card
only works for the manually-reachable columns (`backlog`/`todo`/`on_hold`)
— `in_progress` and `completed` are timer-only, per the backend's state
machine, so those columns aren't drop targets. Each task card has inline
timer controls that only ever offer actions valid for that task's current
state (see `backend/README.md` for the exact rules).

## Design system

Tailwind CSS v4 (CSS-first config — see the `@theme` block in
`src/app/globals.css`) plus a small set of hand-built primitives in
`src/components/ui/` styled in the shadcn/ui idiom, rather than a hand-rolled
global stylesheet. The look is a clean, light, "modern SaaS" aesthetic
(Linear/Notion/ClickUp-adjacent): white cards on a light gray page, an
indigo accent (`brand-*` theme colors), Inter as the typeface, and generous
whitespace. Charts on `/reports` use `recharts`, colored from the `dataviz`
skill's validated light-mode categorical palette.

## Known follow-up

`npm audit` reports moderate/high advisories in `postcss`, a build-time
transitive dependency of Next.js with no runtime exposure in this app.
Clearing them requires the Next.js 16 major upgrade (React 19); left for a
deliberate follow-up rather than bundled into this scaffold.
