# Team-Scoped Boards, Per-Team Swim Lanes & Board Renaming (Round C) — Design Document

Status: draft for db-admin review, then backend-dev + designer hand-off
(design only, nothing here is implemented)
Owner: solution architect
Source of truth: `docs/PRD.md` (`## Kanban Board`)
Reviewed against: `backend/app/models.py` (`BoardConfig`, `ManualTimeEntrySettings`,
`SwimlaneField`, `Team`, `User`, `Task`, `Permission`, `Role`/`RolePermission`),
`backend/app/routers/{admin,tasks,teams}.py`, `backend/app/schemas.py`,
`backend/app/services/{authz,teams,migrations}.py`,
`frontend/src/app/board/{page,BoardScreen}.tsx`, `frontend/src/board/store.tsx`,
`frontend/src/board/lanes.ts`, `frontend/src/app/admin/swim-lanes/page.tsx`,
`frontend/src/lib/{types,api}.ts`.

Same conventions as `docs/design/custom-roles-design.md` and
`docs/design/auth-rbac-design.md`: **CONFIRMED** = current behavior already
matches the target, no rework; **GAP** = a real problem found in current code;
**PROPOSED CHANGE** = a new rule/endpoint/column this design introduces.

This round was explicitly anticipated by `BoardConfig`'s own docstring
("mid-restructuring in a separate, not-yet-built round (team-scoped
boards)") and by `ManualTimeEntrySettings`'s docstring (kept as its own table
"rather than folded into `BoardConfig` itself" for exactly this reason). This
design honors both of those forward notes.

---

## 0. PRD gap this round must be explicit about

The PRD's `## Kanban Board` section is **team-agnostic** — it describes swim
lanes, workflow, and custom fields as single, app-wide settings, with no
mention of teams, multiple boards, or board naming. Round A (Department/Team
org structure) shipped *underneath* the PRD without the PRD itself ever being
updated to describe team-scoped views. This design is therefore **extending**
the PRD's Kanban Board section, not implementing an already-specified
requirement — flagging this explicitly per the standing instruction to flag
conflicts/gaps rather than silently deviate. Recommend the PRD gets a short
addendum once this ships ("swim lanes and the workflow view are configurable
per team; a team's board can optionally be given its own display name")
rather than leaving the written spec permanently behind the shipped app.

---

## 1. What "a team-scoped board" means, concretely

### 1.1 Decision: no new `Board` entity — `Team` is the scoping unit, exactly one implicit board per team

**Options considered:**

| Option | Shape | Pros | Cons |
|---|---|---|---|
| A. `Team` *is* the board (no new entity, board = "the filtered view of tasks where `Task.team_id` matches") | A team-scoped settings row keyed 1:1 by `team_id` holds the board's per-team config (swim-lane field, display name) | Matches the precedent already set by `?project=<id>` scoping (§1.2) — no new "Board" concept, just a new filter dimension on the existing task list; `Task.team_id` already exists and is a plain FK, exactly the shape needed; zero new relationship cardinality questions | A team can never have more than one board, and a board can never span multiple teams — acceptable per the brief's own framing ("one board per team") |
| B. Separate `Board` entity, FK'd to `Team`, allowing N:1 or M:N mapping | `boards` table with its own `id`, optionally `team_id` (nullable, or a join table for many-to-many) | Future-proofs "a team could have two boards" or "one board could span two teams" | Nothing in the brief, the PRD, or `Task.team_id`'s existing shape (a single plain FK, not a join table) asks for or supports that cardinality; it would require *also* adding a `Task.board_id` (redundant with `team_id`) or reinterpreting `team_id` as derived from a board, a much bigger change with no stated requirement driving it |

**Chosen: Option A.** Justification, tied to existing code: `Task.team_id`
already exists, is already the column a task is scoped to at creation time
("a task's home team... set once at creation... never re-derived" —
`models.py`), and is already a plain nullable FK to `teams.id` — exactly the
shape "one board per team" needs with zero task-table changes. This mirrors
the project's own established pattern for "scope a board view to one
dimension": `?project=<id>` → `BoardProvider projectId` → `GET
/tasks?project_id=` already does precisely this for projects, with no
separate "Board" entity for a project either. Round C repeats that shape for
teams rather than inventing a new one.

**Consequence**: "the board" is not a new noun in the domain model. What's
new is (a) a `team_id` filter on the existing task list (§4), and (b) a new
settings row, one per team, holding the per-team swim-lane field and
optional display name (§2/§3). A `Team` and "its board" are 1:1 by
construction — you cannot create a board without a team, and every active
team automatically has one (lazily materialized on first read/write, exactly
like today's singleton `BoardConfig` row is lazily created, §7).

### 1.2 The "no team selected" board (today's default view) still needs to exist

Not every task has a `team_id` (nullable, permanent state — an unplaced new
hire's tasks, or a task an admin deliberately leaves team-less). Not every
caller wants to scope to one team either (an admin overseeing everything
wants "all tasks," the same default view that exists today). **PROPOSED
CHANGE, minimal**: keep the existing global `board_config` singleton table
(`id="default"`) completely unchanged, and redefine its scope in
documentation/docstring only: it is now specifically the settings for the
**unscoped view** — "all tasks, or tasks with no team" — the same view `GET
/board` (no `team` param) already renders today. No schema change to that
table, no migration needed for it (see §7.1) — it already lazily
get-or-creates exactly as needed. This is a deliberate minimal-blast-radius
choice: rather than repurposing the existing table's meaning by force-fitting
a `team_id = NULL` sentinel row into a new per-team table (§2), the existing
table simply keeps doing exactly what it does today, permanently representing
the one thing that was never a team in the first place.

---

## 2. Per-team swim lanes — new table, not a `Team` column

### 2.1 Options considered

| Option | Shape | Pros | Cons |
|---|---|---|---|
| A. Add `swimlane_field`/`board_name` columns directly onto `Team` | `Team.swimlane_field: SwimlaneField`, `Team.board_name: str | None` | Fewer tables, no join needed to render a team row | Breaks this codebase's own established convention: `BoardConfig`/`ManualTimeEntrySettings` are already **both** kept as separate singleton tables specifically to avoid "entangling a... setting with a table about to change shape" (`ManualTimeEntrySettings` docstring, verbatim) — `Team` is org-structure data (department, manager, active members) consumed by RBAC/reporting/reminders; board display concerns have nothing to do with that and would pollute every `TeamRead` response and every org-structure query with board-only fields |
| B. New table, one row per team, 1:1 via `team_id` as primary key | `team_board_configs(team_id PK/FK, board_name, swimlane_field, updated_at)` | Matches the established "separate table per concern" convention exactly (`BoardConfig`, `ManualTimeEntrySettings`); keeps `Team`/`TeamRead` untouched — zero risk to the already-shipped org-structure/RBAC rounds; a team without a board-config row yet is a completely ordinary, harmless state (lazy-create, same idiom as `get_board_config`) | One extra join/query per team when rendering the admin swim-lanes screen — negligible, same cost `GET /admin/board-config` already pays for the singleton |

**Chosen: Option B**, for the reason stated in the table — this project has
already made this exact call twice (`BoardConfig`, `ManualTimeEntrySettings`)
and documented *why* board-ish settings don't belong bolted onto an unrelated
core entity. Doing the same thing a third time, onto `Team` this time, would
be the one inconsistent choice.

### 2.2 Exact proposed schema (for db-admin, §7)

```python
# models.py — PROPOSED CHANGE (new table)
class TeamBoardConfig(Base):
    """One row per Team (Round C: team-scoped boards), holding exactly the
    two things an admin/team-manager can configure about that team's board:
    which field groups cards into swim lanes, and the board's own display
    name (independent of Team.name -- see the docstring on `board_name`
    below for why these are deliberately different fields).

    Kept as its own table rather than columns on `Team` itself -- same
    established precedent as `BoardConfig`/`ManualTimeEntrySettings` above,
    both singleton tables deliberately separated from unrelated entities for
    exactly this reason (see `ManualTimeEntrySettings`'s own docstring).
    `Team` stays pure org-structure data (department, manager, active
    members); this table stays pure board-presentation data. RBAC/reporting/
    reminders code that reads `Team`/`TeamRead` is completely unaffected by
    this table's existence.

    `team_id` is the primary key (not a separate synthetic uuid + a unique
    column) -- this is a true 1:1 extension of `Team`, not a many-per-team
    settings list, so the FK itself doubles as the uniqueness guarantee with
    no separate index needed for that purpose.

    Lazily created on first `GET`/`PATCH
    /teams/{team_id}/board-config` for a team that doesn't have a row yet --
    identical idiom to `routers/admin.py::get_board_config`'s existing
    lazy-create-if-missing pattern for the id="default" singleton. A brand
    new team therefore has no row here until its board is first viewed or
    configured; the read endpoint (§4) returns the same defaults
    (`swimlane_field=ASSIGNEE`, `board_name=None`) either way, so this is
    invisible to callers.

    `swimlane_field` reuses the *existing* `SwimlaneField` Postgres native
    enum type as-is (see `BoardConfig.swimlane_field`'s own `Enum(...)`
    column) -- this round adds zero new enum members, so there is no
    `ALTER TYPE ... ADD VALUE` risk of the kind flagged on `AuditAction`
    above; a second column referencing an already-existing Postgres enum
    type is an ordinary `CREATE TABLE`, not a type change.

    `board_name` is nullable and, when null, the display layer falls back to
    the team's own `Team.name` (e.g. "Engineering") -- so an admin who never
    bothers to rename a board sees a sensible default with zero extra admin
    action required. Deliberately a *separate* field from `Team.name`, not a
    rename of `Team.name` itself -- see the design decision writeup in §3
    for why conflating the two would be a mistake.

    Left behind, deliberately, when a team is soft-deactivated
    (`Team.is_active=False`): this row is not deleted or otherwise touched.
    A deactivated team's board-config row becomes unreachable through normal
    navigation (the team no longer appears in the team switcher, §6) but
    is not orphaned in any FK sense (`Team` rows are never hard-deleted,
    per `routers/teams.py::delete_team`'s existing soft-delete-only
    contract) and would simply become live again if the team were ever
    reactivated -- consistent with this codebase's general "never silently
    lose settings behind a soft-deactivation" posture.
    """

    __tablename__ = "team_board_configs"

    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    board_name: Mapped[str | None] = mapped_column(String, nullable=True)
    swimlane_field: Mapped[SwimlaneField] = mapped_column(
        Enum(SwimlaneField), default=SwimlaneField.ASSIGNEE, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    team: Mapped["Team"] = relationship()
```

No changes to `Team`, `TeamRead`, `TeamCreate`, `TeamUpdate`, or any RBAC/
reporting/reminders code that touches `Team` — this is a purely additive new
table.

---

## 3. Board renaming — a new field, not a rename of `Team.name`

### 3.1 What exactly is renamed

**Decision: a new, board-specific `board_name` field (§2.2), independent of
`Team.name`.** `Team.name` stays the org-structure identity used everywhere
else in the app: the Departments/Teams admin screens, the manager picker's
"which team" grouping, `GET /users?team_id=` filtering, reports/reminders
that resolve "which team is this task/user in," and the audit trail. Renaming
*that* would ripple into every one of those surfaces for a reason (board
cosmetics) that has nothing to do with any of them.

`board_name` is purely a display label for the Kanban board screen's header
and the team switcher (§6). When null (the default, including for every
existing team on day one, §7), the UI displays `Team.name` as the effective
board title — so "rename the board" is opt-in cosmetic polish, never a
requirement to keep the board usable.

### 3.2 Why not just let admins rename `Team.name` and call it done

Considered and rejected: it would conflate two independent admin actions
("this team is now called X for org-chart/reporting purposes" vs. "I want
this team's Kanban screen to show a friendlier title") behind one field,
and would make "rename the board to something obviously not the team's name"
(the brief's own example — "Sprint Board" instead of "Engineering Team's
board") impossible to do without also relabeling the team everywhere else in
the app, which is very likely not the intent behind an admin who wants a
punchier board title.

---

## 4. API contract

### 4.1 `GET /teams/{team_id}/board-config` — **NEW**

Any authenticated user (mirrors `GET /admin/board-config`'s current
open-read, and `GET /teams`'s open-read) — reading a team's swim-lane
grouping/board name is not sensitive.

- `404` if `team_id` doesn't reference an existing team (active or
  inactive — same "you can still look up something that exists" precedent as
  reading other soft-deleted entities by id elsewhere in this codebase).
- `200` →
```json
{
  "team_id": "uuid",
  "board_name": "Sprint Board",
  "swimlane_field": "assignee",
  "updated_at": "iso8601",
  "can_manage": false
}
```
Lazily creates the row (defaults: `board_name=null`, `swimlane_field="assignee"`)
if none exists yet, exactly like `get_board_config` does today for the
`id="default"` row. `can_manage` is a **server-computed** field (§5.3,
finalized): `has_permission(current_user, Permission.MANAGE_BOARD_CONFIG)`,
the same boolean `PATCH`'s own `403` check evaluates — included on `GET` so
the frontend never re-derives authorization in JS (§5.3).

### 4.2 `PATCH /teams/{team_id}/board-config` — **NEW**

Request (both optional, partial update):
```json
{ "board_name": "Sprint Board", "swimlane_field": "priority" }
```
- `board_name: str | None` — explicit `null` clears back to the `Team.name`
  fallback; omitted key leaves it unchanged (standard `exclude_unset`
  partial-update semantics, matching `TeamUpdate`/`UserUpdate` elsewhere).
- `swimlane_field: SwimlaneField | None` — same enum as today's
  `BoardConfigUpdate.swimlane_field`, no new values.
- `404` if `team_id` doesn't exist.
- `403` if the caller lacks `MANAGE_BOARD_CONFIG` (§5.2 — **finalized**:
  admin-only, generalized as-is, no team-manager carve-out).
- `200` → same shape as §4.1's `GET`, **plus** `can_manage: bool` (§5.3).

### 4.3 `GET /admin/board-config` / `PATCH /admin/board-config` — **CONFIRMED, unchanged**, plus one additive field

Kept exactly as they are today (route, schema, `MANAGE_BOARD_CONFIG`
permission gate, singleton `id="default"` row) — now understood to mean
specifically "the settings for the unscoped/no-team board view" (§1.2), not
"the app's one and only board." **This is not a breaking change** to either
endpoint's contract; only their documented meaning narrows now that
per-team configs exist alongside them.

**One additive change, applied here too (§5.3, finalized)**:
`BoardConfigRead` gains the same server-computed `can_manage: bool` field
`TeamBoardConfigRead` gets (§4.1) — `has_permission(current_user,
Permission.MANAGE_BOARD_CONFIG)`. This is the fix for the pre-existing
`frontend/src/board/store.tsx` bug (§5.3): both the global and per-team
screens must compute "can I edit this" the same server-side way, not have
one screen fixed and the other left on the old broken `role === "admin"`
client-side check.

### 4.4 `GET /tasks?team_id=` — **NEW filter param**, precedent-matched to `manager_id`

```python
# routers/tasks.py::list_tasks — PROPOSED CHANGE
team_id: str | None = None
...
if team_id:
    query = query.filter(Task.team_id == team_id)
```
Added as a **plain additional filter**, positioned alongside the existing
`manager_id`/`project_id`/`assignee_id` filters, applied *before* the
ownership/`VIEW_ALL_TASKS`/**same-team** visibility filter that runs at the
end of `list_tasks` (§5.1, finalized — the visibility filter itself gains a
new branch this round, not just this new query param).

No changes to `TaskRead`, `TaskCreate`, or `TaskUpdate` — `Task.team_id`
already exists and is already serialized (§ Round A).

---

## 5. Visibility & authorization — both forks decided (finalized)

Both authorization questions this design originally raised as open
questions have since been decided by the user. This section states the
final rules and the exact code changes; §8 below no longer lists them as
open.

### 5.1 Decision 1 (FINALIZED): shared team visibility — Option B, fully effective, not gated behind a new permission

**Decision**: any user whose own `User.team_id` matches a task's
`Task.team_id` may **view** that task — on the board list, by opening its
detail panel, and reading its comments and audit trail. This is a new,
additive branch on the existing visibility floor, automatic for every user
(not gated behind a new permission key — Option C from the original draft
is rejected; every team member gets this for free, the same way "the
assignee's manager can view" is automatic today, not permission-gated).
**View only** — `can_edit_task` is not touched, so a teammate can see a
card but cannot edit or delete it, start/pause/stop its timer, or otherwise
mutate it, exactly the same separation-of-concerns the custom-roles design
established in its §1.4.2 for `VIEW_ALL_TASKS`.

**Confirmed scope, resolving the question raised while drafting this
section**: this must be **fully effective**, not list-only — the exact same
"partial effect" trap Round B3 (`docs/design/custom-roles-design.md` §1.4)
had to explicitly resolve for `VIEW_ALL_TASKS`. The stated intent ("a shared
board my team works from") only makes sense if a teammate can actually open
a card, read its comments, and see its audit trail — a board where you can
see a card exists but get a `403` opening it would be a worse experience
than no visibility at all. Since `GET /tasks/{id}`, `GET/POST
/tasks/{id}/comments`, and `GET /tasks/{id}/audit` are all gated by
`assert_can_view_task` (unchanged call sites), adding the branch to
`can_view_task` itself (rather than only to `list_tasks`'s filter) makes it
fully effective everywhere in one change, exactly like `VIEW_ALL_TASKS`'s
branch already does.

#### 5.1.1 `can_view_task` — new branch, appended last, after `VIEW_ALL_TASKS`

```python
# services/authz.py — PROPOSED CHANGE
def can_view_task(current_user: User, task: Task) -> bool:
    if current_user.role == UserRole.ADMIN:
        return True
    if current_user.id in (task.assignee_id, task.created_by_id):
        return True
    if task.assignee and task.assignee.manager_id == current_user.id:
        return True
    if has_permission(current_user, Permission.VIEW_ALL_TASKS):
        return True
    if task.team_id is not None and current_user.team_id == task.team_id:   # NEW — Round C
        return True
    return False
```
Positioned as the **last** `if` before `return False`, strictly after every
existing branch (floor admin, ownership, manager-of-assignee,
`VIEW_ALL_TASKS`) — same legibility rationale as §1.4.1 of the custom-roles
design: this ordering doesn't change runtime behavior (every branch
independently `return True`s), it just keeps the new, Round-C-specific rule
visibly set apart at the bottom for a future reader diffing this function.

The `task.team_id is not None` guard is deliberate, not incidental: without
it, `current_user.team_id == task.team_id` would evaluate `None == None` as
`True` for two people who are *both* unplaced (`team_id=NULL`), silently
granting every team-less user visibility into every other team-less user's
team-less tasks — a real, if narrow, unintended widening nobody asked for.
Requiring `task.team_id is not None` closes that off: this branch only ever
fires for an *actual* team match, never for "neither of us has a team."

#### 5.1.2 `list_tasks` — the equivalent branch in the filter composition

```python
# routers/tasks.py::list_tasks — PROPOSED CHANGE
conditions = [
    Task.assignee_id == current_user.id,
    Task.created_by_id == current_user.id,
    Task.assignee.has(User.manager_id == current_user.id),
]
if current_user.team_id is not None:          # NEW — Round C, same guard as §5.1.1
    conditions.append(Task.team_id == current_user.team_id)
if not has_permission(current_user, Permission.VIEW_ALL_TASKS):
    query = query.filter(or_(*conditions))
```
Same guard rationale as §5.1.1: the new condition is only appended when the
*caller* has a real team, so a team-less caller's result set is completely
unaffected by this change (still exactly assignee/creator/managed-report
tasks, as today).

#### 5.1.3 `can_edit_task` — deliberately untouched

```python
# services/authz.py — CONFIRMED, no change
def can_edit_task(current_user: User, task: Task) -> bool:
    if current_user.role == UserRole.ADMIN:
        return True
    return current_user.id in (task.assignee_id, task.created_by_id)
```
No `team_id` branch is added here, for the identical reason the custom-roles
design gave for not extending this function with `VIEW_ALL_TASKS` (§1.4.2
there): doing so would let "can see my team's board" silently escalate into
"can edit/delete any teammate's task," an unrelated and much larger
capability than shared visibility. A teammate viewing another's card sees
it read-only — no edit/delete controls, no timer controls (`can_control_time_entry`
is likewise untouched, so a teammate cannot pause/resume/stop another
teammate's timer either).

#### 5.1.4 Net effect, stated as a table

| Actor | `GET /tasks` (list, team-filtered) | `GET /tasks/{id}` / comments / audit | `PATCH`/`DELETE /tasks/{id}`, timer control |
|---|---|---|---|
| True floor admin | ✅ (unchanged) | ✅ (unchanged) | ✅ (unchanged) |
| Assignee / creator / assignee's manager | ✅ (unchanged) | ✅ (unchanged) | ✅ if assignee/creator (unchanged) |
| Same-team teammate (not assignee/creator/manager) | ✅ **(new)** | ✅ **(new, fully effective)** | ❌ 403 — unchanged, view only |
| Different-team user, no other relationship | ❌ excluded (unchanged) | ❌ 403 (unchanged) | ❌ 403 (unchanged) |

### 5.2 Decision 2 (FINALIZED): board-config management stays admin-only — Option A

**Decision**: `MANAGE_BOARD_CONFIG` is generalized as-is to gate `PATCH
/teams/{id}/board-config` for **every** team, exactly like it already gates
the single global `PATCH /admin/board-config` today. **No team-manager
carve-out is built.** A team's own manager has no special authority over
their team's board-config beyond whatever role/permissions they'd otherwise
hold — they need `MANAGE_BOARD_CONFIG` like anyone else. This keeps the
permission catalog's existing shape completely uniform: every `manage_*`
key in this codebase is global-or-nothing (compare `manage_teams`), and this
round does not introduce the first exception.

**Consequence, stated plainly**: the `can_manage_team_board(current_user,
team)` structural function sketched in an earlier draft of this section is
**out of scope, not just unused** — no such function is added to
`services/authz.py`. `PATCH /teams/{id}/board-config`'s gate is a single
line, identical in shape to the existing global endpoint's:

```python
# routers/teams.py — PROPOSED CHANGE
assert_has_permission(current_user, Permission.MANAGE_BOARD_CONFIG)
```

No new `Permission` catalog entry, no new authz function, no change to
`can_edit_task`/`can_view_task` from this decision — this section is purely
"reuse the existing global permission for the new per-team endpoint too."

### 5.3 Frontend implication — fixing a pre-existing bug while building this round's new authorization surface

The board-config `PATCH` gate (§5.2) must be computed **server-side** and
exposed to the frontend, not re-derived in JavaScript — this matters because
the *existing* single-global-board screen already gets this wrong today
(**GAP, pre-existing, not introduced by this round, but directly relevant
since this round builds the same kind of control a second time**):
`frontend/src/board/store.tsx`'s `canManageBoardConfig = session.currentUser
?.role === "admin"` checks the legacy `role` string literally, not
`has_permission(..., MANAGE_BOARD_CONFIG)` — so a custom role already
granted that permission via the Round B3 Roles screen cannot actually see
the "Group lanes by" control enabled on the *existing* board, even though
the backend would accept their `PATCH`. Building this round's new per-team
screen on the same broken pattern would just create a second, differently-
broken copy of the same bug.

**Fix, applied to both endpoints identically (§4.1, §4.3)**: `BoardConfigRead`
and the new `TeamBoardConfigRead` both gain a server-computed `can_manage:
bool` field — `has_permission(current_user, Permission.MANAGE_BOARD_CONFIG)`,
the same boolean each `PATCH` handler evaluates before raising its own
`403`. The frontend reads this field directly (`boardConfig.can_manage`)
instead of re-deriving permission logic from `currentUser.role` — one fix,
applied consistently to the global screen and the new per-team screen alike,
not a fix for one and a lingering bug in the other. See §9 for the explicit
hand-off item.

---

## 6. Frontend surface

### 6.1 Board page — team switcher, `?team=<id>` URL param

Mirrors the existing `?project=<id>` → `BoardProvider projectId` pattern
exactly (`frontend/src/app/board/page.tsx`):

```tsx
// frontend/src/app/board/page.tsx — PROPOSED CHANGE
function BoardWithProject() {
  const params = useSearchParams();
  const projectId = params.get("project");
  const teamId = params.get("team");                 // NEW
  return (
    <BoardProvider projectId={projectId} teamId={teamId}>
      <BoardScreen />
    </BoardProvider>
  );
}
```

`BoardProvider` (`frontend/src/board/store.tsx`) gains a `teamId` prop,
threaded into `listParams()` alongside `projectId`/`managerId` (`teamId ?
{ teamId } : {}`), and fetches `api.getTeamBoardConfig(teamId)` instead of
`api.getBoardConfig()` when a team is selected, falling back to the existing
`api.getBoardConfig()` call when `teamId` is null (the unscoped view, §1.2).
`setSwimlaneField`/a new `setBoardName` call the team-scoped `PATCH` instead
of the global one when `teamId` is set.

**Naming collision to flag for the designer, found while reading
`BoardScreen.tsx`**: the board **already** has a `<Select>` labeled
`"Team"` today (`board.managerFilter`/`board.setManagerFilter`,
`BoardScreen.tsx` lines ~116-131) — but it is actually a **manager** filter
("Everyone" / "`{manager.full_name}`'s team"), unrelated to the org-chart
`Team` entity this round introduces. Round C's real, `Team`-entity-based
switcher must **not** reuse the label "Team" for a second, different
concept on the same screen — recommend relabeling the existing control to
something like **"Manager"** or **"Direct reports"** and reserving **"Team"**
for the new org-chart-team switcher. Flagging this explicitly rather than
letting the designer discover two same-labeled-but-different filters after
the fact.

New switcher, same `<Select>` pattern, populated from the already-fetched
`GET /teams` list (active only):
```tsx
<label>
  <span>Team</span>
  <Select value={teamId ?? ""} onChange={(e) => router.push(`/board?team=${e.target.value}`)}>
    <option value="">All teams</option>
    {teams.map((t) => (
      <option key={t.id} value={t.id}>{t.board_name ?? t.name}</option>  {/* effective board name, §3 */}
    ))}
  </Select>
</label>
```
When a team is selected, the header shows the effective board name (e.g.
"Sprint Board" or, if `board_name` is null, the team's own name) instead of
the generic "Kanban board" title, mirroring how the project filter already
shows "Filtered to project X — clear filter" today.

### 6.2 Admin swim-lanes screen — list + detail, not a single setting anymore

`frontend/src/app/admin/swim-lanes/page.tsx` currently renders one `<Select>`
for the single global setting. **PROPOSED CHANGE**: replace with a
list+detail pattern, matching the Roles/Teams admin screens' own convention
rather than inventing a new one:

- A table: one row per active team (Name, Board name, Swim-lane field,
  Actions), sourced from `GET /teams` joined client-side with
  `GET /teams/{id}/board-config` per row (or a small batch, since team
  counts are small in this org-management app — same assumption `GET
  /roles` already makes about small catalog sizes).
- Plus one fixed, always-present row at the top for "Unassigned / all
  tasks" (the existing global `GET/PATCH /admin/board-config`, §4.3) — not
  renamable (no `board_name` concept exists for it, §1.2), same single
  `<Select>` UI the current screen already has, just visually demoted to
  "one row among several" rather than the whole screen.
- Each team row's "Edit" action opens a small panel/inline form with two
  fields: Board name (text input, placeholder = the team's own name) and
  Group lanes by (the existing `<Select>` of `SWIMLANE_FIELDS`). Disabled
  entirely (with a tooltip) for a caller whose `can_manage` (§5.3) comes
  back `false` for that row.

---

## 7. Schema needs — for db-admin

### 7.1 What's new

One new table only: `TeamBoardConfig` / `team_board_configs`, exact shape in
§2.2. `BoardConfig` (existing table) is **completely untouched** — no column
added, no data moved out of it, no row deleted from it (§1.2/§4.3).

### 7.2 Migration for an already-deployed database — this IS a real backfill concern, not just a new-table create

Unlike `RolePermissionAuditEntry` (a brand-new table with **zero** existing
data to reconcile, per the custom-roles design's §6.2), `board_config`
**already has one live row** (`id="default"`) with a real, possibly
admin-changed `swimlane_field` value on any deployed environment. The new
`team_board_configs` table starts empty, and unlike the org-structure
backfill (`_migrate_org_structure_backfill`, which back-filled a **required**
column with no legitimate "unset" default), leaving `team_board_configs`
empty at first is not actually broken — the lazy-create-on-first-read
behavior (§2.2) means every team simply gets `swimlane_field=ASSIGNEE,
board_name=None` (the same hardcoded default that's already
`BoardConfig.swimlane_field`'s own column default) the first time its board
is opened.

**The question for db-admin to decide**: is lazy-create-with-hardcoded-default
sufficient, or should the migration proactively seed one `team_board_configs`
row per existing active team, copying the *current* value of the singleton
`board_config.swimlane_field` — so that every existing team's board looks
and groups identically to how the single global board already looks today,
rather than silently resetting anyone whose admin had previously changed the
global setting away from the `ASSIGNEE` default? **My recommendation**: do
the proactive backfill, precisely to avoid a silent, surprising regression
for any team whose swim-lane grouping isn't already the default — same
"never silently change behavior on deploy" principle
`_migrate_org_structure_backfill`'s own docstring already states explicitly
(the "General" bootstrap team/department precedent). Sketch, following that
function's exact idiom (schema-state-keyed, not data-state-keyed, so it only
runs once and never re-fires on a later restart):

```python
# services/migrations.py — PROPOSED CHANGE, for db-admin to build/verify
def _migrate_team_board_config_backfill(engine: Engine, inspector) -> None:
    # team_board_configs is a brand-new table -- already created by
    # Base.metadata.create_all before this runs (same precondition as
    # _migrate_org_structure_backfill's departments/teams tables).
    # This function's only job: seed one row per currently-active team,
    # copying the existing global board_config.swimlane_field value, the
    # first time this table is empty -- so no existing team's board silently
    # changes grouping behavior on deploy.
    with engine.begin() as conn:
        already_seeded = conn.execute(text("SELECT 1 FROM team_board_configs LIMIT 1")).fetchone()
        if already_seeded is not None:
            return
        global_row = conn.execute(
            text("SELECT swimlane_field FROM board_config WHERE id = 'default'")
        ).fetchone()
        default_field = global_row[0] if global_row is not None else "assignee"
        team_ids = conn.execute(text("SELECT id FROM teams WHERE is_active = true")).fetchall()
        now = datetime.utcnow()
        for (team_id,) in team_ids:
            conn.execute(
                text(
                    "INSERT INTO team_board_configs (team_id, board_name, swimlane_field, updated_at) "
                    "VALUES (:team_id, NULL, :swimlane_field, :updated_at)"
                ),
                {"team_id": team_id, "swimlane_field": default_field, "updated_at": now},
            )
```
Note this is **checked by data state** ("table is empty") rather than schema
state, unlike `_migrate_org_structure_backfill`'s explicit preference for
schema-state checks — flagging this divergence explicitly for db-admin to
confirm is actually safe here: my reasoning is that, unlike `users.team_id`/
`tasks.team_id` (where `NULL` is a legitimate *permanent* per-row state that
must never be re-backfilled on restart), a **missing row** in
`team_board_configs` is not a legitimate permanent state to preserve once
seeding has happened once — every team is supposed to end up with exactly
one row, lazily or via this backfill, and a genuinely new team created
*after* this migration ran simply gets its row lazily on first read (§2.2),
never touched by this function again since the table won't be empty by
then. Still, this is exactly the kind of idempotency-condition judgment call
db-admin should verify rather than take on my say-so alone.

### 7.3 Specific questions for db-admin (mirroring custom-roles design's §6.4 style)

1. **Backfill approach**: confirm §7.2's proactive backfill (copying the
   global default into every active team) is correct/wanted, versus simply
   relying on lazy-create-with-hardcoded-default and accepting that any team
   whose org previously changed the global swim-lane setting away from
   `ASSIGNEE` will silently reset to `ASSIGNEE` per-team until someone
   notices and re-sets it. I lean toward the proactive backfill (§7.2) but
   want this confirmed given the explicit divergence from the
   schema-state-keyed idempotency idiom noted there.
2. **Enum reuse**: confirm that `Enum(SwimlaneField)` on a second table
   (`team_board_configs.swimlane_field`) referencing the same, already-
   existing Postgres enum type as `board_config.swimlane_field` is a
   conflict-free, ordinary `CREATE TABLE` on both SQLite and Postgres — no
   dialect-specific handling needed (my reading: yes, since no new enum
   *values* are introduced and the type itself already exists by the time
   this table is created — but this is exactly the class of "verified
   empirically, not assumed" check this project's own `AuditAction` near-
   miss history says should never be skipped).
3. **FK/soft-delete interaction**: `team_id` is `ForeignKey("teams.id")` and
   `primary_key=True`, with `Team` rows never hard-deleted (only
   soft-deactivated). Confirm there's no scenario in this codebase where a
   `Team` row *is* hard-deleted (I found none — `routers/teams.py::
   delete_team` is soft-delete-only, mirroring `Department`) that would ever
   orphan a `team_board_configs` row; if one exists that I missed, this
   table would need the same "409 if referenced" guard pattern
   `role_permission_audit_entries` uses for `Role`.
4. **Indexing**: no non-PK index is proposed on `team_board_configs` — every
   query is a PK lookup (`WHERE team_id = :id`) or a small full scan (the
   admin list screen, §6.2, at most "number of teams" rows). Confirm no
   index is needed beyond the primary key, given the expected table size is
   bounded by the number of teams in this org (small, per the existing
   `GET /roles`-style "small catalog" assumption elsewhere in this project).
5. **`change_type`/enum-safety precedent, restated for this table**: no new
   native-Postgres-enum member is introduced anywhere in this design
   (`SwimlaneField` is reused unchanged) — confirm db-admin agrees this
   round carries **zero** `ALTER TYPE ... ADD VALUE` risk, unlike the
   `AuditAction`/`MANUAL_TIME_LOGGED` precedent that motivated the standing
   "scrutinize enum changes extra hard" rule this project now has.

### 7.4 db-admin sign-off (finalized)

Reviewed `TeamBoardConfig` (§2.2) and the migration/backfill approach (§7.2),
verified empirically against a real local Postgres 16 instance (not just
SQLite) and against SQLite, per this project's own "prove it against real
data" standard. `models.py`/`services/migrations.py` are implemented as
described below; see
`backend/tests/test_migration_team_board_config_with_real_data.py` for the
empirical proof (4 tests, all passing on both backends).

**Schema (§2.2)**: shipped exactly as proposed, no changes — `team_id` as
primary key, `board_name` nullable `String`, `swimlane_field`
`Enum(SwimlaneField)` defaulting to `ASSIGNEE`, `updated_at`
default/`onupdate`. No additional index (see Q4 below).

**Q1 — Backfill approach: proactive backfill, but *not* the §7.2 sketch's
exact idempotency shape.** Confirmed the proactive backfill is the right
call (silently resetting every team to `ASSIGNEE` on deploy, when an org
already customized the global setting, is exactly the kind of surprise
regression this project's `_migrate_org_structure_backfill` precedent says
to avoid). **Overrode the sketch's "is the whole table empty" gate**,
however: that check is a single point of failure — one stray row (e.g. a
team's row lazily created via `GET /teams/{id}/board-config` before this
migration ever got a chance to run, or a row surviving a restored backup)
makes the table "non-empty" and would silently skip the backfill for
*every other* active team forever, with no automatic way to recover (this
project's standing constraint rules out a manual operator fix). Shipped
instead: a **per-team, insert-if-missing** check
(`_migrate_team_board_config_backfill`), re-evaluated on every startup —
the same idempotency *class* `_migrate_rbac_schema_backfill` already uses
and defends (data-state, `WHERE ... IS NULL`-shaped, safe to re-run
indefinitely specifically because "this team has no row yet" is never a
legitimate permanent state to preserve, unlike `team_id IS NULL` on
`users`/`tasks`). This function only ever `INSERT`s a row that doesn't
exist; it never `UPDATE`s one that does, so an admin's own `PATCH` (or an
earlier lazy-create) is never clobbered by a later run — verified directly
in the test file (an admin-customized row survives a second backfill run
that also picks up a newly-created team). Deactivated teams are excluded by
the `WHERE t.is_active = true` filter itself, not merely "left alone once
seeded" — verified their rows are never created.

**Q2 — Enum reuse: confirmed safe, empirically, not by analogy.** Built both
`board_config` and `team_board_configs` with `Enum(SwimlaneField)` against a
real local Postgres 16 schema: exactly one native `swimlanefield` enum type
is created, shared by both columns (`inspector.get_columns` reflects the
identical `ENUM(...)` type object on each; `pg_type`/`pg_namespace` confirms
a single row, scoped to the schema being tested, filtered by
`nspname='public'`-equivalent — the standing lesson about enum types being
schema-scoped like tables was applied when writing this check). This is the
same already-shipped pattern `TaskStatus` already uses across `Task.status`
and `TaskStatusEvent.from_status`/`to_status` — an ordinary, conflict-free
`CREATE TABLE`, not a type change, on both dialects.

**A real bug caught in the process (not hypothetical)**: the design doc's
§7.2 sketch's fallback default — `default_field = ... else "assignee"` (the
enum member's lowercase `.value`) — is the exact `AuditAction`-class mistake
this project already has one documented near-miss for, applied to a second
enum column. Confirmed empirically: inserting that lowercase string into
`team_board_configs.swimlane_field` **crashes outright on Postgres**
(`psycopg2.errors.InvalidTextRepresentation: invalid input value for enum
swimlanefield: "assignee"`) — which would have broken `ensure_schema_migrations`,
and therefore app startup, on any fresh-ish deploy where `board_config` has
no row yet but at least one active team exists (true of every deploy, since
the bootstrap "General" team always exists). On SQLite the same bad insert
does *not* raise at insert time (no real enum enforcement there), but
**silently produces a row that then raises `LookupError` the next time
anything reads it back through the ORM** — worse, because it fails later,
somewhere else, disconnected from the migration that caused it. Fixed to use
`SwimlaneField.ASSIGNEE.name` (`"ASSIGNEE"`) — the same uppercase-member-name
convention `_migrate_rbac_schema_backfill` already established for exactly
this reason. Both failure modes are reproduced directly in
`test_naive_lowercase_fallback_would_have_crashed_on_postgres`.

**Q3 — FK/soft-delete interaction: confirmed, not just trusted.** Read
`routers/teams.py::delete_team` directly: it only ever sets
`team.is_active = False` (after a 409 guard on active members) — no code
path anywhere in `backend/app/` issues `db.delete(team)` or a raw `DELETE
FROM teams`. `team_board_configs.team_id`'s FK to `teams.id` can therefore
never be orphaned by an application code path. No occupancy-guard pattern
(like `role_permission_audit_entries`'s 409-on-referenced-role) is needed
here.

**Q4 — Indexing: confirmed, no additional index needed.** Every read is
either a PK lookup (`WHERE team_id = :id`, the `GET`/`PATCH` per-team
endpoints) or a full scan bounded by "number of teams in this org" (the
admin list screen) — the same "small catalog" sizing assumption already
applied to `GET /roles`. No non-PK index added.

**Q5 — `ALTER TYPE` risk: confirmed zero.** No new `SwimlaneField` member is
introduced anywhere in this round; the type is reused unchanged. Verified
there is no `ALTER TYPE swimlanefield ADD VALUE` (or equivalent) anywhere in
`_migrate_team_board_config_backfill` — the function only ever `SELECT`s
from and `INSERT`s into ordinary tables.

**Verified**: `backend/tests/test_migration_team_board_config_with_real_data.py`
(4 tests: non-default-value propagation + inactive-team exclusion +
admin-customization-survives-rerun + new-team-self-heals, on real local
Postgres 16; the naive-lowercase-fallback crash reproduction, on real local
Postgres 16; the empty-`board_config`-fallback path, on real local Postgres
16; the completely-fresh-database path, on SQLite) — all passing, plus the
full existing backend suite (301 tests) on both `sqlite:///./time_tracking.db`
and a local `postgresql://app_user:app_password@localhost:5432/time_tracking`,
zero regressions.

**Recommendation for fullstack-dev-1 (not this round's scope to implement)**:
when building the lazy-create path for `GET`/`PATCH
/teams/{team_id}/board-config` (§4.1), consider defaulting a lazily-created
row to the *current* `board_config.swimlane_field` value (mirroring what the
backfill does for pre-existing teams) rather than a hardcoded `ASSIGNEE` —
otherwise a team created between backfill runs and its first board view
could still land on a different default than its sibling teams got. Not a
blocker; either choice is schema-safe, this is an application-layer
consistency nicety.

---

## 8. Other open questions / ambiguities (not silently resolved)

Both authorization forks originally raised here (team-membership task
visibility, and team-manager board-config authority) have been decided by
the user — see §5.1/§5.2 (finalized) for the resolutions. The items below
are the remaining, genuinely open items.

1. **Should `GET /users` / the assignee picker gain a `team_id` filter
   too?** Out of explicit scope for this round (not asked for, and the
   board's assignee picker already works fine unscoped), but noted since a
   team-scoped board might reasonably want "only show me assignee options
   from this team" as a follow-on UX nicety. Not building it now — flagging
   so it isn't assumed to be part of this round if a reviewer expects it.

2. **What happens to a task's board placement if its team is later
   deactivated?** `Task.team_id` is never re-derived (Round A, unchanged by
   this design) — a task homed to a now-deactivated team keeps that
   `team_id` forever, and (per §6.1) that team's board becomes unreachable
   through the normal team switcher (deactivated teams aren't listed). The
   task itself doesn't disappear — it still shows up on the unscoped "All
   teams" board (§1.2) and in any other filter (`assignee_id`, etc.) that
   doesn't go through the team switcher. This is a natural consequence of
   existing soft-deactivation behavior elsewhere (deactivated entities keep
   their historical references), not a new decision, but flagging it since
   it's a real, slightly surprising edge case an admin might hit
   ("where did my team's in-flight tasks go after I deactivated the team")
   worth a line in the admin-facing docs/UI copy, not code. Relatedly, since
   §5.1 now grants same-team view access: a user reassigned off a team
   (`User.team_id` changed) immediately loses the new teammate-view
   privilege for that team's tasks on their very next request (the check is
   live, not cached) — this is correct/expected, not a gap, just noted for
   completeness since it's a direct consequence of §5.1's branch being
   evaluated from `current_user.team_id` fresh on every call.

3. **PRD addendum.** Per §0 — recommend the PRD's `## Kanban Board` section
   gets a short addition documenting that swim lanes/workflow are now
   per-team-configurable, a team's board can be independently named, and
   team membership now grants shared view access to a team's tasks (§5.1),
   once this ships, so the PRD stays the accurate source of truth this
   project's own conventions depend on.

---

## 9. Hand-off summary

Both authorization decisions (§5.1, §5.2) are now **final** — nothing in
this hand-off is blocked or pending on the orchestrating session/user.

**For db-admin**: review §2.2 (new `TeamBoardConfig` table, exact shape
given), §7 (migration/backfill approach for the already-live
`board_config` singleton data, exact sketch given), and answer the five
numbered questions in §7.3. `BoardConfig`/`ManualTimeEntrySettings`
themselves need zero schema changes (the `can_manage` field added to both
their `Read` schemas in §5.3 is a Pydantic/response-shape addition only, not
a column).

**For fullstack-dev-1 (backend)**:
1. Add `TeamBoardConfig` to `models.py` (§2.2) and the migration in
   `services/migrations.py` (§7.2, pending db-admin sign-off).
2. `GET`/`PATCH /teams/{team_id}/board-config` in `routers/teams.py`
   (§4.1/§4.2), gated by `assert_has_permission(current_user,
   Permission.MANAGE_BOARD_CONFIG)` (§5.2, finalized — no team-manager
   carve-out, no new authz function).
3. `services/authz.py::can_view_task` — add the new same-team branch,
   appended last (§5.1.1, exact code given). `can_edit_task` and
   `can_control_time_entry` are **not** touched (§5.1.3).
4. `routers/tasks.py::list_tasks` — add the `team_id` filter param (§4.4)
   and the equivalent same-team branch to the ownership-filter composition
   (§5.1.2, exact code given, including the `current_user.team_id is not
   None` guard).
5. `BoardConfigRead`/new `TeamBoardConfigRead` (`schemas.py`) both gain
   `can_manage: bool`, computed the same way in both `GET` handlers (§5.3,
   §4.1, §4.3) — this is also the fix for the pre-existing frontend bug
   below, so it should ship as one coherent change, not two.

**For fullstack-dev-2 (frontend integration)**:
1. `?team=<id>` URL param and `BoardProvider teamId` prop (§6.1),
   `api.getTeamBoardConfig`/`api.updateTeamBoardConfig` in `lib/api.ts`, the
   admin swim-lanes screen's list+detail rework (§6.2).
2. **Fix the pre-existing `canManageBoardConfig` bug (§5.3), applied to
   both screens**: `frontend/src/board/store.tsx`'s `canManageBoardConfig =
   session.currentUser?.role === "admin"` must be replaced with
   `board.boardConfig.can_manage` (the new server-computed field, §4.3) for
   the existing global board-config control, **and** the new per-team
   screen (§6.2) must read `can_manage` off `TeamBoardConfigRead` the same
   way from the start — do not build the new per-team screen first and fix
   the old global one separately; both should land together so the fix
   isn't inconsistent between the two screens.

**For designer**: the "Team" label collision on the existing board screen
(§6.1) needs a naming decision before the new team switcher ships alongside
the existing manager filter; the admin swim-lanes screen's new list+detail
layout (§6.2); the board header's effective-name display (`board_name ??
team.name`); and, per §5.1, the new same-team card visibility means a
teammate's card can now appear on the board read-only to people who aren't
its assignee/creator/manager — worth a subtle visual affordance (e.g. the
card simply has no drag handle / edit affordance for a read-only viewer)
rather than looking identical to a card the viewer can act on.
