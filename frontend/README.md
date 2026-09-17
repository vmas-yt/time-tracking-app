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

Follows the **Wise-Inspired-design-analysis** system documented in
`/DESIGN.md` (the project has several named design analyses in that file;
this app implements that one specifically). Tailwind CSS v4 (CSS-first
config — see the `@theme` block in `src/app/globals.css`, where every token
name mirrors `DESIGN.md`'s `{colors.*}` names) plus a small set of
hand-built primitives in `src/components/ui/` (`Button`, `Card`, `Badge`,
`Input`, `Select`).

Signature traits: a lime-green `primary` CTA accent (`#9fe870`, text
`on-primary` near-black) used sparingly for primary actions and the active
nav tab; a sage-tinted `canvas-soft` page background with white `canvas`
cards — surface contrast *is* the elevation, so cards carry no border or
shadow; `rounded-xl` (24px) as the canonical card/button radius; Inter as
the typeface, bold headings approximating Wise Sans' heavy display weight.
Charts on `/reports` are colored from Wise's semantic + accent tokens
(`positive`, `accent-cyan`, `warning-deep`, `negative`, `ink-deep`).

Redesigning to a different named analysis in `DESIGN.md` means re-deriving
`globals.css`'s `@theme` tokens and the `ui/` primitives from that
analysis's `colors`/`typography`/`spacing`/`rounded`/`components` blocks —
the rest of the app (`KanbanBoard`, pages, etc.) consumes those primitives
and shouldn't need to change.

## Known follow-up

`npm audit` reports moderate/high advisories in `postcss`, a build-time
transitive dependency of Next.js with no runtime exposure in this app.
Clearing them requires the Next.js 16 major upgrade (React 19); left for a
deliberate follow-up rather than bundled into this scaffold.
