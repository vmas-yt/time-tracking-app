# Custom Roles & Granular Permissions (Round B3) — Design Document

Status: draft for backend-dev + designer hand-off (design only, nothing here
is implemented)
Owner: solution architect
Source of truth: `docs/PRD.md`
Reviewed against: `backend/app/models.py` (`Role`, `RolePermission`, `User`),
`backend/app/services/authz.py`, `backend/app/services/users.py`,
`backend/app/services/migrations.py` (RBAC Round B1/B2 sections),
`backend/app/routers/{admin,departments,teams,projects,tasks,time_entries,
reports,notifications,users}.py`, `backend/app/schemas.py`,
`frontend/src/app/admin/users/page.tsx`.

Same conventions as `docs/design/auth-rbac-design.md` and
`docs/design/custom-fields-admin-design.md`: **CONFIRMED** = current behavior
already matches the target, no rework; **GAP** = a real problem found in
current code; **PROPOSED CHANGE** = a new rule/endpoint/column this design
introduces.

---

## 0. Recap of the floor this design must not touch

Per `services/authz.py` and `services/users.py`, three things read the
**legacy `User.role` enum column directly, forever**, and this design does
**not** change that:

- `assert_admin()` — the hard gate on every existing `assert_admin(...)` call
  site that isn't converted below.
- `can_view_task()` / `can_edit_task()` — their admin branch (`current_user.
  role == UserRole.ADMIN`).
- `is_last_active_admin()` / `would_strip_last_active_admin()` — the
  last-admin lockout guard.

`role_key()` (resolves `role_id -> Role.key`, generic, already
custom-role-safe since Round B2) is the read helper non-floor checks use.
This design adds `has_permission()` alongside it, same file, same
"non-floor" status.

**Update (finalized decision, §1.4)**: the user has since decided
`can_view_task()` should gain one additive `has_permission()` branch,
appended strictly *after* its hardcoded admin/ownership branches, never
replacing or reordering them — the floor's admin check still runs first and
unconditionally. `can_edit_task()` is **not** extended, precisely to avoid a
view-permission escalating into edit rights — see §1.4 for the full
reasoning and exact code. `assert_admin()` and the last-active-admin guard
remain completely untouched, as originally stated above.

---

## 1. The permission catalog

### 1.1 `manage_roles_permissions` is categorically excluded — confirmed by design, not just by convention

There is **no permission key for managing roles/permissions at all**. All
`/roles*` endpoints (§2) are gated by `assert_admin()` directly — the same
floor function every other admin-only mutation used before this round —
**never** by `has_permission()`. Consequences, each satisfying the standing
constraint explicitly:

- It is not a member of the in-code `Permission` enum (§1.3), so it is
  physically impossible to pass it to `PUT /roles/{id}/permissions` — that
  endpoint's own request schema rejects it with a `422` like any other
  unknown string, no special-case code needed.
- Since it's never a real permission, it can never be "revoked from admin"
  (admin was never depending on a *stored* grant for it — admin's power over
  `/roles*` comes from `assert_admin()`'s hardcoded floor check, identical to
  how it already gates `/departments`, `/teams`, `/projects` today).
- There is therefore no code path, through this new UI or API, that can ever
  leave the system with zero users able to manage roles/permissions: that
  capability is pinned to the same floor that already guarantees "zero users
  able to log in as admin" is unreachable (`is_last_active_admin`/
  `would_strip_last_active_admin`, unchanged, §4).

### 1.2 Admin's implicit-all-permissions status is unaffected

Per `RolePermission`'s existing docstring, admin is never represented by
stored rows. `has_permission()` (§3) special-cases `user.role ==
UserRole.ADMIN` (the floor column, not `role_key()`) as an unconditional
`True`, mirroring `assert_admin`'s own check exactly — so this round doesn't
change what "being admin" already grants; it only adds a way for **other**
roles to be granted a subset of it, one key at a time.

### 1.3 The catalog itself — derived from the actual router audit

`Permission` (new `str, enum.Enum` in `models.py`, alongside `Role`/
`RolePermission` — **not** a DB column type; `RolePermission.permission_key`
stays the plain, unvalidated-at-DB-level `String` column its docstring
already commits to. This enum is purely an application-layer validation/
authoring aid, exactly what that docstring calls "a later round's (B3) job.")

| Key | Meaning (precise) | Endpoints gated |
|---|---|---|
| `manage_departments` | Create/rename/deactivate departments | `POST/PATCH/DELETE /departments`; also unlocks `include_inactive=true` on `GET /departments` |
| `manage_teams` | Create/rename/reassign-manager/deactivate teams | `POST/PATCH/DELETE /teams`; unlocks `include_inactive=true` on `GET /teams` |
| `manage_projects` | Create/rename/delete projects | `POST/PATCH/DELETE /projects` |
| `manage_custom_fields` | Create/edit/delete custom field definitions | `POST/PATCH/DELETE /admin/custom-fields` |
| `manage_dropdown_options` | Add/relabel/deactivate category, priority, and custom-field-select options | `POST/PATCH/DELETE /admin/dropdown-options`; unlocks `include_inactive=true` on `GET /admin/dropdown-options` |
| `manage_board_config` | Change the swim-lane grouping field | `PATCH /admin/board-config` |
| `manage_manual_entry_settings` | Change the manual/retroactive time-log policy (`max_days_back`) | `PATCH /admin/manual-entry-settings` |
| `archive_tasks` | Archive/unarchive any task; see archived tasks in board/list views | `POST /tasks/{id}/archive`, `/unarchive`; unlocks `include_archived=true` on `GET /tasks` |
| `view_all_tasks` | See every task in the board **list**, and open/view any single task, its comments, and its audit trail, regardless of assignee/creator/manager relationship | `GET /tasks` (list) ownership-filter bypass; `GET /tasks/{id}`, `GET/POST /tasks/{id}/comments`, `GET /tasks/{id}/audit` — via `can_view_task`, extended in §1.4 (Decision 1, finalized) |
| `view_all_time_entries` | Read **and take administrative control (pause/resume/stop)** of any user's or any manager's time entries | `GET /time-entries?user_id=`, `?manager_id=` bypass; **plus** `POST /time-entries/{id}/pause`, `/resume`, `/stop` on any entry — via the new `assert_can_control_time_entry`, §1.4 (Decision 1, finalized). Does **not** extend to editing/deleting the underlying task itself — see §1.4's escalation analysis. |
| `view_reports_all` | See cycle-time/lead-time/throughput/CFD/control-chart data for every task, not just own+direct-reports | All 5 `GET /reports/*` endpoints |
| `view_all_reminders` | See the "hasn't logged time" reminder list for every user, not just self (+ direct reports) | `GET /notifications/reminders` |

That's the full grantable catalog — 12 keys. Nothing else in the audited
routers had a role-gated decision point that both (a) isn't already floor
(`assert_admin`/`can_edit_task`) in a way this round leaves alone, per §1.4,
and (b) isn't a structural/ownership rule out of scope per the brief (e.g.
"only the assignee can start a timer," "only the task's assignee may log
manual time for it," `validate_manager_id`'s `role_key(...) == "employee"`
eligibility check — all untouched, see §1.5).

### 1.4 Decision 1 (FINALIZED): extending the floor, precisely, without a view→edit escalation

**This was an open question in the original draft; the user has decided:
extend the floor.** `can_view_task` gains an additive `has_permission()`
branch. `can_edit_task` does **not** — resolved precisely below, because a
naive "add the same branch to both" would have created exactly the
accidental view→edit escalation the user asked me to check for.

#### 1.4.1 `can_view_task` — new branch, appended last, after every existing hardcoded branch

```python
# services/authz.py — PROPOSED CHANGE
def can_view_task(current_user: User, task: Task) -> bool:
    if current_user.role == UserRole.ADMIN:
        return True
    if current_user.id in (task.assignee_id, task.created_by_id):
        return True
    if task.assignee and task.assignee.manager_id == current_user.id:
        return True
    if has_permission(current_user, Permission.VIEW_ALL_TASKS):   # NEW — appended last
        return True
    return False
```
The new branch is the **last** `if` before the final `return False`, strictly
after the floor admin check and every structural ownership/management check.
This ordering doesn't change runtime behavior (each branch independently
`return True`s; the floor branch already short-circuits first for a real
admin regardless of where the new line sits) — it matters for **legibility**:
a future reader diffing this function sees the floor and existing structural
rules completely untouched at the top, with the new, additive,
permission-system-sourced capability clearly set apart at the bottom. This
makes `view_all_tasks` **fully** effective: `GET /tasks/{id}`,
`GET/POST /tasks/{id}/comments`, and `GET /tasks/{id}/audit` (all gated by
`assert_can_view_task`) now work for a holder of this permission, not just
the list endpoint.

#### 1.4.2 `can_edit_task` — deliberately left **byte-for-byte unchanged**

```python
# services/authz.py — CONFIRMED, no change
def can_edit_task(current_user: User, task: Task) -> bool:
    if current_user.role == UserRole.ADMIN:
        return True
    return current_user.id in (task.assignee_id, task.created_by_id)
```

**Why not add a `VIEW_ALL_TASKS` branch here too**: `can_edit_task` gates
`PATCH/DELETE /tasks/{id}` directly. `view_all_tasks` is named, documented,
and presented to admins in the UI (§5.1) as a *view* permission. If
`can_edit_task` also checked `has_permission(current_user,
Permission.VIEW_ALL_TASKS)`, granting a role the ability to merely **see**
every task would silently also let it **edit and delete** every task — an
unambiguous, accidental privilege escalation from a view-labeled permission,
exactly the failure mode flagged for re-examination. There is no
`edit_any_task` (or equivalent) permission in the catalog (§1.3 already
explains why: no non-floor call site existed for it before this decision),
and this design does not introduce one now either — `can_edit_task` stays
floor-only (true admin, assignee, or creator), full stop, in this round. If
a future round wants a genuinely delegable "edit any task" capability, it
needs its own dedicated, separately-named permission key added to the
catalog and its own explicit sign-off, not a reuse of `view_all_tasks`.

#### 1.4.3 Time entries: a dedicated wrapper, not a `can_edit_task` branch, so `view_all_time_entries` reaches pause/resume/stop without touching general task edit rights

`pause_timer`/`resume_timer`/`stop_timer` (`routers/time_entries.py`) call
`_get_owned_entry(...)` (ownership-or-permission fetch, avoids a 404) and
then, today, `assert_can_edit_task(current_user, entry.task)` — the **same**
shared function `update_task`/`delete_task` use. Adding a
`view_all_time_entries` branch directly to `can_edit_task` would have the
identical escalation problem as §1.4.2, just via a different permission:
granting "view/control any time entry" would silently also unlock
`PATCH`/`DELETE` on the entry's *task*, which is a different, broader
capability than "operate this timer." So `can_edit_task` is not touched for
this either. Instead, a new, narrowly-scoped function:

```python
# services/authz.py — NEW
def can_control_time_entry(current_user: User, entry: TimeEntry) -> bool:
    """Whether current_user may pause/resume/stop this time entry.

    The ordinary case is identical to can_edit_task on the entry's task
    (floor admin, assignee, or creator) -- checked first, unconditionally,
    exactly as today. The only addition is a narrow, time-entry-scoped
    operational override: a role holding view_all_time_entries may also
    pause/resume/stop *any* entry, without that permission leaking into
    general task edit/delete rights, which stay gated by the untouched
    can_edit_task above.
    """
    if can_edit_task(current_user, entry.task):
        return True
    return has_permission(current_user, Permission.VIEW_ALL_TIME_ENTRIES)


def assert_can_control_time_entry(current_user: User, entry: TimeEntry) -> None:
    if not can_control_time_entry(current_user, entry):
        raise HTTPException(status_code=403, detail="Not authorized to control this time entry")
```

`pause_timer`/`resume_timer`/`stop_timer` replace their
`assert_can_edit_task(current_user, entry.task)` call with
`assert_can_control_time_entry(current_user, entry)`. `update_task`/
`delete_task` are **not** touched — they keep calling `assert_can_edit_task`
exactly as today, so general task field-edit/delete rights are completely
unaffected by this change.

`_get_owned_entry` itself (the fetch-avoid-404 step) also gets the direct
`has_permission()` conversion already planned in §3.1 — restated precisely
here since it composes with the above:
```python
# routers/time_entries.py — PROPOSED CHANGE
def _get_owned_entry(db: Session, entry_id: str, current_user: User) -> TimeEntry:
    entry = db.get(TimeEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Time entry not found")
    if entry.user_id == current_user.id:
        return entry
    if has_permission(current_user, Permission.VIEW_ALL_TIME_ENTRIES):
        return entry
    raise HTTPException(status_code=404, detail="Time entry not found")
```
(`has_permission()` already returns `True` unconditionally for a floor admin
per §3's own definition, so the old explicit `role_key(...) == "admin"`
branch collapses into the single `has_permission()` check above with no
loss of coverage.)

#### 1.4.4 Net effect, stated as a table

| Actor | `GET /tasks/{id}` / comments / audit | `PATCH`/`DELETE /tasks/{id}` | `pause`/`resume`/`stop` on someone else's entry |
|---|---|---|---|
| True floor admin | ✅ (unchanged) | ✅ (unchanged) | ✅ (unchanged) |
| Assignee / creator | ✅ (unchanged) | ✅ (unchanged) | ✅ own entries (unchanged) |
| Custom role, `view_all_tasks` only | ✅ **(new, fully effective)** | ❌ 403 (unchanged) | n/a |
| Custom role, `view_all_time_entries` only | ❌ 403 (no task-view grant) | ❌ 403 | ✅ **(new, fully effective)** |
| Custom role, neither | ❌ 403 (unless structurally owns/manages) | ❌ 403 | ❌ 404 |

No combination of the granted permissions in this catalog lets a non-floor,
non-owning custom-role holder edit or delete a task's fields — only true
floor-admin, the assignee, or the creator can do that, exactly as before
this round.

### 1.5 Explicitly excluded from the catalog: `manage_users`

`create_user`/`update_user`/`delete_user`/`reset_password` (`routers/
users.py`) stay gated by `assert_admin()` only — **not** converted to a
`has_permission()` check, and no `manage_users` key exists in the catalog.

**Reasoning**: `PATCH /users/{id}` is the one endpoint that sets `role` and
`role_id` — i.e., it's how permissions actually get attached to a person.
Granting a custom role the ability to manage users would let its holder set
any other user's `role` to `"admin"` (the legacy enum accepts any
`UserRole` value from any caller who clears `assert_admin` today) or assign
any `role_id`, including a future powerful custom role — a direct back door
around "you cannot grant `manage_roles_permissions`," just one hop removed.
Treating full user administration (including role assignment) as
floor-admin-only, exactly like it is today, closes that hole the same way
excluding `manage_roles_permissions` itself does. This is a deliberate scope
boundary, not an oversight — flagging it explicitly since it means Round B3
does not let an admin delegate "add/deactivate/reset-password for
employees" to a non-admin custom role. If that's wanted later, it needs its
own narrower design (e.g. a `manage_users` permission that can create/edit/
deactivate but is hard-blocked from ever writing `role`/`role_id`), out of
scope here.

### 1.6 A related existing gap, found and fixed as part of this audit: `notifications.py`'s literal `role_key() == "manager"` branch

`reminder_candidates` today is:
```python
if role_key(current_user) == "admin": scope = everyone
elif role_key(current_user) == "manager": scope = current_user's direct reports
else: scope = self only
```
This couples "sees direct reports' reminders" to *holding the literal
builtin manager role*, not to *structurally having direct reports*
(`User.manager_id == current_user.id`). Once custom roles are real, a user
holding a custom role (e.g. "Team Lead") who genuinely has direct reports
via `manager_id` would silently fall into the `else` branch and lose
visibility into their team's compliance reminders — a real regression this
feature would otherwise introduce, not a hypothetical. **PROPOSED CHANGE**
(bundled into this round since it's a direct side effect of shipping custom
roles that hold real people, not a hypothetical Round B4 nice-to-have):
```python
if current_user.role == UserRole.ADMIN or has_permission(current_user, Permission.VIEW_ALL_REMINDERS):
    scope = db.query(User)
else:
    scope = db.query(User).filter(or_(User.id == current_user.id, User.manager_id == current_user.id))
```
This is behavior-preserving for every existing employee/manager/admin (a
manager's direct-reports scope is now derived structurally instead of by
role key, which is the same set for every manager today), and correctly
extends to any future role — builtin or custom — that happens to have
direct reports.

---

## 2. API contract: role CRUD + permission assignment

New router `backend/app/routers/roles.py`, prefix `/roles`, same
list/create/patch/delete-or-deactivate shape as `departments.py`/`teams.py`.

### 2.1 `GET /roles` — any authenticated user

Open-read, same precedent as `GET /departments`/`GET /teams` (the Users
admin screen's role picker needs this for every caller who can reach that
screen, and there's no sensitive data in a role's name/permission list).

```json
[
  { "id": "uuid", "key": "employee", "name": "Employee", "is_builtin": true,
    "permission_keys": [], "created_at": "iso8601" },
  { "id": "uuid", "key": "admin", "name": "Admin", "is_builtin": true,
    "permission_keys": [], "created_at": "iso8601" },
  { "id": "uuid", "key": "team-lead", "name": "Team Lead", "is_builtin": false,
    "permission_keys": ["manage_teams", "view_all_tasks"], "created_at": "iso8601" }
]
```
`permission_keys: []` for **every** builtin (including admin) — admin's is
implicit (§1.2); employee/manager hold no rows and grant nothing beyond
their hardcoded structural behavior (§1.5's boundary, restated: builtins are
not permission-configurable in this round, see §2.4).

No `assigned_user_count` field — matches `DepartmentRead`/`TeamRead`'s
existing minimalism; the frontend derives occupancy client-side by filtering
the already-loaded `users` list by `role_id`, same pattern
`UserProfilePanel`'s "direct reports" already uses.

### 2.2 `POST /roles` — admin only (`assert_admin`)

Request: `{ "name": "Team Lead" }` (`min_length=1`).

- Server generates `key` by slugifying `name` (lowercase, non-alnum runs →
  single `-`, trim leading/trailing `-`, cap at 64 chars); on collision with
  an existing `Role.key`, append `-2`, `-3`, ... until unique. `key` is
  **not** client-settable — keeps it a stable, generated identifier the way
  `role_key()` and the sync logic in `services/users.py` already treat every
  role's key as immutable and machine-usable.
- New row: `is_builtin=False`, zero `RolePermission` rows (admin grants them
  afterward via §2.4).
- `201` → `RoleRead`. `400` if `name` is blank/whitespace-only. `403` if not
  admin.

### 2.3 `PATCH /roles/{id}` — admin only

Request: `{ "name": "New Name" }` — **rename only**. `key` and `is_builtin`
are immutable after creation (same rationale as `DropdownOption.value`
being immutable: `key` is what `role_key()` and every downstream check
resolve against; silently repointing it would reinterpret history with no
audit trail).

- `404` not found. `403` not admin.
- `409` if `role.is_builtin` — built-in names are fixed and seeded; this
  endpoint never touches them (avoids "did renaming 'Manager' to something
  else silently change what code branches key off of" confusion — nothing
  in this codebase keys off a role's `name`, only its `key`, but keeping
  builtins fully immutable here is the simplest, safest rule to state).
- `200` → `RoleRead`.

### 2.4 `PUT /roles/{id}/permissions` — admin only — full replacement

Request: `{ "permission_keys": ["manage_teams", "view_all_tasks"] }` — a
`list[Permission]` (the enum from §1.3) in the Pydantic schema, so an
unknown string (including `"manage_roles_permissions"`, which is not a
member) is rejected by FastAPI's own validation as a `422`, no hand-written
check needed.

- Full-set replacement (delete all existing `RolePermission` rows for this
  role, insert the new set), not incremental add/remove — matches "setting a
  role's granted permission set" and how a checkbox-grid UI naturally
  submits (§5).
- `409` if `role.is_builtin` — **built-in roles cannot hold explicit
  `RolePermission` rows in this round.** Their capabilities stay exactly
  what's hardcoded today (admin: everything, implicit; manager/employee:
  whatever structural rules like `manager_id` scoping already give them).
  Rationale: granting `manage_teams` to the builtin *Employee* role would
  change behavior for every employee in the org at once — a much larger,
  fuzzier blast radius than "configure one new named role," and conflicts
  with builtins being the fixed reference points Round B1/B2 established.
  An admin who wants "employees, but also able to manage teams" creates a
  new custom role instead.
- `404` role not found. `403` not admin.
- `200` → `RoleRead` (updated `permission_keys`).
- **Decision 2 (FINALIZED — reverses the original draft's deferral)**:
  this endpoint now **writes an audit record** of exactly what changed, who
  changed it, and when. Diff the requested `permission_keys` set against the
  role's current `RolePermission` rows *before* replacing them; for every
  key present in the diff, insert one `RolePermissionAuditEntry` row
  (`change_type="added"` or `"removed"`), all sharing one `batch_id`
  generated once for this call. **No rows are written if the diff is
  empty** (re-submitting the same set is a no-op, not a loggable event).
  Full schema in §6 (new table — this is a real, needed migration, unlike
  the original draft's "no schema change" conclusion). Read via
  `GET /roles/{id}/audit`, §2.7.

### 2.5 `DELETE /roles/{id}` — admin only — real hard delete (not soft), with an occupancy guard

Unlike `Department`/`Team`/`User`/`DropdownOption` (all soft-deactivated,
because *other* rows — tasks, time entries — must keep resolving their
historical labels forever), a `Role` has no such downstream historical
dependents: nothing except `User.role_id` points at it, and
`RolePermission` rows cascade-delete cleanly (`cascade="all, delete-orphan"`,
already on the `Role.permissions` relationship). Once truly unoccupied, a
hard delete loses nothing — this is the same shape of decision as
`DELETE /projects/{id}` (hard delete, 409-if-referenced), not the
Team/Department pattern.

- `404` not found.
- `409` if `role.is_builtin` — built-ins are never deletable, full stop
  (`"Cannot delete a built-in role."`).
- `409` if **any** `User` row (active **or** inactive) currently has
  `role_id == this role's id` (`"Cannot delete a role assigned to one or
  more users. Reassign them first."`). **Deliberate divergence from the
  Team/Department occupancy guard**, which only checks `is_active` members
  — spelled out in §6.3, since it's a real reason, not an inconsistency.
- **`409` if any `RolePermissionAuditEntry` row references this role**
  (`"Cannot delete a role with permission-change history — it would erase
  the audit trail."`) — **new guard, added by Decision 2 (§6)**. Same
  "never silently erase audit trail" principle, and near-identical message,
  as `delete_task`'s existing "Cannot delete a task with logged time
  entries — it would erase the audit trail and reporting history" guard
  (`routers/tasks.py`). Concrete consequence, stated plainly rather than
  left implicit: **once a custom role has had its permission set changed
  even once, it can never be deleted again** — only renamed, emptied of
  permissions, and unassigned from every user. This mirrors how a task
  becomes permanently undeletable the moment any time is logged against it;
  it is a deliberate trade-off in favor of preserving history, not an
  oversight. A role that was created and then deleted *without* ever having
  `PUT /roles/{id}/permissions` called on it (e.g. a mis-clicked "+ Add
  role" immediately undone) has no audit rows and remains freely deletable.
- Otherwise: `db.delete(role)`, commit, `204 No Content` (matches
  `DELETE /admin/custom-fields/{id}`'s response shape — also a real hard
  delete with nothing left to return, unlike the soft-deactivate endpoints
  that return `200` + the greyed-out row).

### 2.6 What happens to users holding a role that's mid-deletion-attempt

Nothing, ever, silently — that's the entire point of §2.5's occupancy guard.
There is no "reassign everyone to a fallback role" auto-behavior; the admin
must explicitly move each affected user to a different role (via the
existing `PATCH /users/{id}` role-assignment path, §4) before the delete
succeeds. This mirrors the Team/Department precedent's philosophy exactly
(block, don't cascade), just enforced against a wider set (all users, not
only active ones — §6.3).

### 2.7 `GET /roles/{id}/audit` — admin only — permission-change history (**NEW, Decision 2**)

Mirrors the naming and shape of the existing `GET /tasks/{id}/audit`
exactly (same "one resource, one nested `/audit` sub-resource" convention),
rather than a top-level `GET /roles/audit` — consistent with how this
codebase already scopes audit history per-resource, not globally.

Gated by `assert_admin()` (floor, matching every other `/roles*` endpoint,
§1.1) — **not** `has_permission()`. Reading who-changed-what-permissions is
itself security-sensitive; it stays exactly as delegable as managing roles
is, i.e. not at all in this round.

- `404` if the role doesn't exist. `403` if not admin.
- `200` → one entry per distinct `batch_id` for this `role_id`, newest
  first, each row's `permission_key`/`change_type` rows folded into
  `added`/`removed` lists server-side:

```json
[
  {
    "batch_id": "uuid",
    "occurred_at": "iso8601",
    "actor": { "id": "uuid", "full_name": "Jane Doe", "email": "jane@company.com" },
    "added": ["manage_projects"],
    "removed": ["manage_teams"]
  },
  {
    "batch_id": "uuid",
    "occurred_at": "iso8601",
    "actor": { "id": "uuid", "full_name": "Jane Doe", "email": "jane@company.com" },
    "added": ["manage_teams", "view_all_tasks"],
    "removed": []
  }
]
```
(Second entry above is the role's original grant, shown oldest-last; first
is a later edit that swapped `manage_teams` for `manage_projects`.)

Built-in roles: always `200` → `[]` (they can never hold `RolePermission`
rows or generate audit rows, §2.4) — not a `404` or `409`, since asking for
a built-in's history is a legitimate, well-defined question with a legitimate,
well-defined (empty) answer.

---

## 3. `has_permission()` — the generic permission-check helper

`backend/app/services/authz.py`, alongside `role_key()`:

```python
def has_permission(user: User, permission: Permission) -> bool:
    """Non-floor permission check for a granted custom-role capability.

    Mirrors assert_admin's floor check for the "admin has everything"
    shortcut (checks the legacy `user.role` column directly, not
    `role_key()`) so this always agrees with the one guarantee that must
    never depend on the new role/permission system being correct. Beyond
    that shortcut, this is purely additive: it can only grant capability a
    custom role was explicitly given via `PUT /roles/{id}/permissions`
    (§2.4), never take anything away from an existing hardcoded check.

    Builtin non-admin roles (employee/manager) always return False here for
    every key, since they can never hold RolePermission rows (§2.4) — their
    behavior is unaffected by this function's existence.
    """
    if user.role == UserRole.ADMIN:
        return True
    if user.role_id is None or user.assigned_role is None:
        return False
    return any(p.permission_key == permission.value for p in user.assigned_role.permissions)
```

No `db: Session` parameter needed — same style as `role_key()`, relying on
the already-attached `assigned_role`/`permissions` relationships lazy-loading
off the `User` instance the caller already has.

### 3.1 Which existing checks convert to `has_permission()` this round

| Current check | File | Converts to |
|---|---|---|
| `assert_admin` on create/update/delete | `departments.py` | `has_permission(current_user, Permission.MANAGE_DEPARTMENTS)` |
| `role_key(...) == "admin"` on `include_inactive` | `departments.py` | same permission |
| `assert_admin` on create/update/delete | `teams.py` | `MANAGE_TEAMS` |
| `role_key(...) == "admin"` on `include_inactive` | `teams.py` | same |
| `assert_admin` on create/update/delete | `projects.py` | `MANAGE_PROJECTS` |
| `assert_admin` on custom-field create/update/delete | `admin.py` | `MANAGE_CUSTOM_FIELDS` |
| `assert_admin` on dropdown-option create/update/delete | `admin.py` | `MANAGE_DROPDOWN_OPTIONS` |
| `role_key(...) == "admin"` on `include_inactive` (dropdown options) | `admin.py` | same |
| `assert_admin` on board-config update | `admin.py` | `MANAGE_BOARD_CONFIG` |
| `assert_admin` on manual-entry-settings update | `admin.py` | `MANAGE_MANUAL_ENTRY_SETTINGS` |
| `assert_admin` on archive/unarchive | `tasks.py` | `ARCHIVE_TASKS` |
| `role_key(...) == "admin"` on `include_archived` | `tasks.py` | `ARCHIVE_TASKS` (reuses the same permission — "can see archived tasks" is the same concept as "manages archiving," not a separate key, keeping the catalog from ballooning) |
| `role_key(...) == "admin"` ownership-filter bypass | `tasks.py` `list_tasks` | `VIEW_ALL_TASKS` — now **fully** effective, §1.4.1 |
| `can_view_task`'s admin-only branch | `services/authz.py` | gains an additive `VIEW_ALL_TASKS` branch, appended last (§1.4.1) — the one, deliberate exception to "floor functions stay untouched," fully specified there |
| `role_key(...) == "admin"` bypass in `_get_owned_entry` | `time_entries.py` | `VIEW_ALL_TIME_ENTRIES` (§1.4.3 — exact replacement code given there) |
| `assert_can_edit_task` call inside `pause_timer`/`resume_timer`/`stop_timer` | `time_entries.py` | replaced by the new `assert_can_control_time_entry` (§1.4.3), which composes the **unchanged** `can_edit_task` with `VIEW_ALL_TIME_ENTRIES` — `can_edit_task` itself is not modified, see §1.4.2/§1.4.3 |
| `role_key(...) == "admin"` in `list_time_entries`'s `user_id`/`manager_id` branches | `time_entries.py` | `VIEW_ALL_TIME_ENTRIES` |
| `role_key(...) == "admin"` in `_scope_to_visible_tasks` | `reports.py` | `VIEW_REPORTS_ALL` |
| `role_key(...) == "admin"` / `== "manager"` three-way branch | `notifications.py` | `VIEW_ALL_REMINDERS` + structural direct-reports fix (§1.6) |

### 3.2 Left alone, deliberately, and why

- `assert_admin` on `users.py` (`create_user`/`update_user`/`delete_user`/
  `reset_password`) — §1.5.
- `assert_admin`'s role-column read itself, and `can_edit_task`'s role-column
  read itself — both stay byte-for-byte unchanged. Note the asymmetry with
  `can_view_task`, which **is** extended this round (§1.4.1) — `can_edit_task`
  is the one floor function this design deliberately does not touch, for the
  view→edit escalation reasons spelled out in §1.4.2/§1.4.3.
- `is_last_active_admin`/`would_strip_last_active_admin` — unchanged, still
  keyed to the legacy `role` column exactly as today (§4 confirms this
  composes correctly with role_id-based assignment).
- `validate_manager_id`'s `role_key(manager) == "employee"` eligibility
  check (`services/users.py`) — **CONFIRMED, no change needed.** This
  already generalized correctly in Round B2: a manager-candidate holding any
  *non-employee* role — builtin manager/admin, or any future custom role —
  already passes this check today, with zero B3 code change. Whether a
  custom-role holder being manager-eligible by default (rather than needing
  a dedicated permission) is desired is worth a sanity check, but I'm not
  flagging it as an open question — it's consistent with the existing rule's
  actual wording ("must reference a user with role 'manager' or 'admin'"
  generalizes to "must reference a user who isn't a plain employee," which
  this system already enforces).
- `start_timer`'s assignee-only check, `add_manual_log`'s assignee-only
  check — ownership rules, out of scope per the brief's own framing.

---

## 4. Assigning any role (built-in or custom) to a user

### 4.1 Schema changes (all additive, no migration — see §6)

```python
# schemas.py
class UserCreate(UserBase):
    role: UserRole | None = None        # CHANGED: was UserRole = EMPLOYEE
    role_id: str | None = None          # NEW
    ...

class UserUpdate(BaseModel):
    role: UserRole | None = None        # unchanged field, new semantics below
    role_id: str | None = None          # NEW
    ...

class UserRead(UserBase, UTCModel):
    role: UserRole | None               # CHANGED: was UserRole (non-optional) — see §4.4, this is a pre-existing bug this round must fix
    role_id: str | None = None          # NEW
    role_name: str                      # NEW — resolved display name, works for builtin and custom alike
    ...
```

### 4.2 Request-time resolution rule (`POST /users`, `PATCH /users/{id}`)

At most one of `role` / `role_id` may be given in a single request — `400`
if both are present and non-null. New shared helper, `services/users.py::
resolve_role_assignment(db, role: UserRole | None, role_id: str | None) ->
tuple[UserRole | None, str]`, replacing the current
`role_id_for_builtin_role`-only call sites:

| Input | Resolution |
|---|---|
| Neither given (create only) | Default: `role=UserRole.EMPLOYEE`, `role_id=<builtin employee row>.id` |
| `role` given | Existing behavior, unchanged: `role_id` = that builtin's row id (`role_id_for_builtin_role`, reused as-is) |
| `role_id` given, resolves to a **builtin** row | Same as above, other direction: `role` is set to the matching `UserRole` enum member (e.g. `role_id` of the builtin "manager" row → `role=UserRole.MANAGER`) — keeps the two columns in sync exactly as the existing docstrings already promise |
| `role_id` given, resolves to a **custom** (`is_builtin=False`) row | `role` is set to `None` — the exact case `User.role`'s own docstring already anticipated ("has no valid value to hold for a user assigned a genuinely custom role... becomes NULL for that user instead") |
| `role_id` given, doesn't resolve to any `Role` row | `400 "role_id does not reference an existing role"` |
| Both given | `400 "role and role_id are mutually exclusive"` |

`create_user`/`update_user` call this instead of `role_id_for_builtin_role`
directly; behavior for every existing caller that only ever sends `role`
(every test, every current frontend call) is **byte-for-byte unchanged**.

### 4.3 Composing with the last-active-admin floor (unchanged function, verified)

`would_strip_last_active_admin(db, user, new_role: UserRole | None)` is
**not modified**. The router computes `new_role` via §4.2's resolution
*before* calling it — so assigning a custom role (which resolves to
`new_role=None`) already correctly triggers "would strip" for the sole
active admin, exactly per that function's own docstring
("`None`... is not `UserRole.ADMIN`, so... correctly treated as 'would
strip admin'"). **CONFIRMED, no change needed** — this function was written
to already be correct for this case (its docstring says so explicitly), and
the router-level resolution in §4.2 is what makes that true in practice.

### 4.4 `UserRead.role` non-optional — pre-existing bug this round must fix

**GAP, found by reading `schemas.py` directly**: `UserRead.role: UserRole`
has no `| None`, but `models.py`'s `User.role` column is already nullable
(Round B2) and the moment any user holds a genuinely custom role, `role`
becomes `NULL` on that row by design (§4.2). Serializing such a user through
the *current* `UserRead` would raise a Pydantic validation error — a
500-class bug latent since Round B2, never triggered only because nothing
has ever actually assigned a custom role until now. Fixing `UserRead.role`
to `UserRole | None` (§4.1) is a required part of this round, not optional
polish — flagging it explicitly since it wasn't asked for by name but is a
direct, provable consequence of the feature actually being usable.

---

## 5. Frontend surface

### 5.1 New admin screen: Roles (`frontend/src/app/admin/roles/page.tsx`)

Same structural pattern as `admin/users/page.tsx`/departments/teams screens:
a table (Name, Key, Type [Built-in/Custom badge], Permissions summary,
Actions) + "+ Add role" button opening a `SlideOver` (`RoleFormPanel`, name
field only — key is server-generated, not shown as an input, optionally
shown read-only after creation for transparency).

- Built-in rows: "Built-in" badge, Edit/Delete actions **disabled** (not
  hidden — same convention `DropdownOption`'s `is_builtin` rows use in the
  existing custom-fields admin screen: greyed with a tooltip explaining why,
  rather than removed from the UI). Permissions column shows `"All
  permissions (implicit)"` for Admin, `"Fixed — not configurable"` for
  Employee/Manager (per §2.4's builtin exclusion).
- Custom rows: Edit (rename) and Delete enabled. Delete button: client-side
  pre-check (filter the already-loaded `users` list by `role_id` — same
  derived-client-side pattern `UserProfilePanel` already uses) to show a
  "N users currently hold this role" warning before the confirm dialog,
  since the server will `409` anyway (§2.5) but a pre-flight warning is
  better UX than a failed round-trip.
- A "Permissions" action per custom role opens a second `SlideOver`
  (`RolePermissionsPanel`) rendering all 12 catalog keys (§1.3) as checkboxes
  grouped into three sections for scannability: **Organization**
  (`manage_departments`, `manage_teams`, `manage_projects`), **Board & task
  admin** (`manage_custom_fields`, `manage_dropdown_options`,
  `manage_board_config`, `manage_manual_entry_settings`, `archive_tasks`),
  **Visibility** (`view_all_tasks`, `view_all_time_entries`,
  `view_reports_all`, `view_all_reminders`) — with a short caption under the
  Visibility group noting the §1.4 partial-effect caveat for
  `view_all_tasks`/`view_all_time_entries` in plain language (e.g. "Lets
  this role see these items in list views; opening an individual task or
  controlling someone else's timer still requires being that task's
  assignee, creator, their manager, or an Admin.") — this caption can now
  be simplified/shortened, since §1.4's finalized decision makes both
  permissions fully effective; kept only to explain that `view_all_tasks`
  is view-only and does not grant task editing/deletion (§1.4.2), which
  remains a real, permanent scope boundary worth stating in the UI. Save
  calls `PUT /roles/{id}/permissions` with the full checked set.
- A "History" action per **custom** role (hidden for built-ins, which never
  have any per §2.7) opens a read-only panel listing `GET /roles/{id}/audit`
  entries newest-first, one line per batch: *"Jane Doe — added
  `manage_projects`, removed `manage_teams` — 2 hours ago"*, reusing the
  existing `formatRelativeTime` helper (`board/format.ts`) per the
  custom-fields-admin design's established precedent for this exact kind of
  timestamp display (`UserProfilePanel`).

### 5.2 Changes to the existing Users screen

`frontend/src/app/admin/users/page.tsx`:
- `ROLE_LABEL[u.role]` (breaks for a custom-role holder, whose `u.role` is
  `null` per §4.4) → `u.role_name` (new field from `UserRead`, §4.1 —
  resolved server-side, works uniformly for builtin and custom).
- The role `<Select>` inside `UserFormPanel` (create/edit) changes from a
  fixed 3-`UserRole` list to fetching `GET /roles` and offering every row
  (built-in and custom) keyed by `role.id`, displaying `role.name`,
  submitting `role_id` in the `POST /users`/`PATCH /users/{id}` payload
  (never `role` from the frontend going forward — simpler than maintaining
  both inputs client-side, and §4.2's resolution already treats a
  builtin-role-id request as fully equivalent to the old `role` field).

---

## 6. Schema needs

### 6.1 Conclusion (REVISED — corrects the original draft): a real migration IS needed, for one new table

The original draft of this doc concluded "no migration, purely additive
data + application logic." **That conclusion no longer holds** — Decision 2
(§2.4/§2.7) requires a genuinely new table, `role_permission_audit_entries`,
to store structured before/after permission-set history. This is a real
schema change and, per this project's standing rule, must go through
db-admin before it's final; §6.4 below is the exact, concrete proposal
db-admin needs to review (this doc alone, since I still have no `Task`/
`Agent` tool to spawn db-admin directly — the orchestrating session will
dispatch db-admin against this section).

Everything from the *original* §6.1 conclusion still holds for the
role/permission-assignment machinery itself (`Role`/`RolePermission` already
exist from Round B1; `User.role_id` and nullable `User.role` already exist
from Round B1/B2; no native-DB-enum column is touched anywhere in this
design) — restated briefly since it's still accurate and still relevant
context for db-admin:
- new **rows** in already-existing tables (custom `Role` rows,
  `RolePermission` rows for them);
- new **application-layer code** (the `Permission` enum, `has_permission()`,
  the `/roles` router, `resolve_role_assignment`);
- new/changed **Pydantic schema fields** (`UserRead.role_id`/`role_name`,
  nullable `role`, `role_id` on create/update) — no DB shape change behind
  any of these.

**What's new and does need a migration**: the one table in §6.4.

### 6.2 New table: `role_permission_audit_entries` (Decision 2)

Modeled on two existing precedents at once, both cited explicitly since
neither alone is a perfect fit:
- `TaskAuditEntry`'s actor/timestamp shape (`actor_id` FK, `occurred_at`) —
  who and when.
- `TaskStatusEvent`'s **normalized, one-row-per-fact** shape (`from_status`/
  `to_status`, no free-text `detail`) rather than `TaskAuditEntry`'s
  free-text `detail` string — because what changed here is precisely a
  structured `(role, permission_key, added|removed)` triple per row, not
  prose, and this codebase's own established convention for "a set of
  values associated with one thing" is **one row per value**
  (`TaskCustomValue`: one row per `(task_id, field_id)`; `DropdownOption`:
  one row per option) — never a comma-separated or JSON-array column. I
  followed that same normalization instead of inventing a denormalized
  `permissions_before`/`permissions_after` blob column, precisely because
  the brief pointed at `TaskCustomValue`/`DropdownOption` as the relevant
  precedent to check, and a blob column would be the first place in this
  entire schema that stores a list-shaped value in a single column.

```python
# models.py — PROPOSED CHANGE (new table)
class RolePermissionAuditEntry(Base):
    """One added-or-removed permission_key for a role, written by a single
    `PUT /roles/{id}/permissions` call (§2.4). One row per changed key, not
    one row per API call -- see TaskCustomValue/DropdownOption for why this
    codebase normalizes multi-value data into rows rather than a list/blob
    column, and TaskStatusEvent for the precedent of a normalized
    one-row-per-fact history table (from_status/to_status) instead of a
    free-text TaskAuditEntry-style `detail` string.

    `batch_id` groups every row written by the same PUT call into one
    displayed history entry (e.g. "Jane Doe: +manage_projects,
    -manage_teams -- 2 hours ago") -- generated once per call in
    application code (`str(uuid.uuid4())`), *not* a column default, since a
    column default would (incorrectly) generate a fresh value per row
    instead of sharing one value across every row from the same call.

    role_id is a real, non-null FK to roles.id -- matching
    TaskAuditEntry.task_id/TaskStatusEvent.task_id's own precedent of a
    real FK to the thing being audited. Consequence, by design (not an
    oversight): `DELETE /roles/{id}` (§2.5) 409s if this role has any row
    here, mirroring `DELETE /tasks/{id}` 409ing if the task has any logged
    time -- same "never let a hard delete silently erase audit history"
    principle, applied to a new entity.

    change_type is a plain, unvalidated-at-DB-level String ("added" |
    "removed"), deliberately not a native Postgres ENUM column -- mirrors
    RolePermission.permission_key's own already-established choice, and
    sidesteps entirely the class of bug this project has already hit once
    for real (see AuditAction's `ALTER TYPE ... ADD VALUE` migration note):
    adding a third change_type value later (if one is ever needed) is then
    a no-op on both backends, not a native-enum migration.
    """

    __tablename__ = "role_permission_audit_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    batch_id: Mapped[str] = mapped_column(String, nullable=False)
    permission_key: Mapped[str] = mapped_column(String, nullable=False)
    change_type: Mapped[str] = mapped_column(String, nullable=False)  # "added" | "removed"
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_role_permission_audit_entries_role_id_occurred_at", "role_id", "occurred_at"),
    )

    role: Mapped["Role"] = relationship()
    actor: Mapped["User"] = relationship()
```

Service-layer write path (`services/roles.py`, new, called from
`PUT /roles/{id}/permissions`):
```python
def record_permission_change(db, role, actor, before: set[str], after: set[str]) -> None:
    added = after - before
    removed = before - after
    if not added and not removed:
        return   # no-op resubmission: write nothing (§2.4)
    batch_id = str(uuid.uuid4())
    now = datetime.utcnow()
    for key in added:
        db.add(RolePermissionAuditEntry(role_id=role.id, actor_id=actor.id, batch_id=batch_id,
                                         permission_key=key, change_type="added", occurred_at=now))
    for key in removed:
        db.add(RolePermissionAuditEntry(role_id=role.id, actor_id=actor.id, batch_id=batch_id,
                                         permission_key=key, change_type="removed", occurred_at=now))
```

Because this is a **brand-new table**, `Base.metadata.create_all` creates it
for free on any fresh database (SQLite dev, or a brand-new Postgres) with
zero migration code, exactly like `ManualTimeEntrySettings`'s own docstring
already notes for its own brand-new-table case ("no `ensure_schema_migrations`
step exists (or is needed) for it"). The only scenario needing an explicit
migration step is **an already-deployed Postgres database** — a plain
`CREATE TABLE role_permission_audit_entries (...)` (with its FKs and index),
run once before deploying the new backend code, same shape as every prior
"new table on a live DB" note in the other two design docs.

### 6.3 FK/occupancy reasoning for `DELETE /roles/{id}` and `User.role_id` (renumbered from the original draft's §6.2 — this is what §2.5 refers to as "§6.3")

**Question I'd ask**: "Given `Role.id` is only referenced by `User.role_id`
(a plain `ForeignKey("roles.id")`, no `ondelete` clause, unenforced on
SQLite / enforced on Postgres per the existing FK-behavior notes elsewhere
in this codebase) — is it safe to hard-`DELETE FROM roles WHERE id = :id`
once no *active* user holds it, or does an inactive-but-still-existing user
row with a stale `role_id` risk an `IntegrityError` on Postgres?"

**My reasoned answer, which is why §2.5's occupancy guard checks *all* users
(active and inactive), not just active ones — a deliberate divergence from
the Team/Department precedent**: yes, this is a real risk. Team/Department's
guard only checks active occupants because deactivating the last active
member/team is itself the thing that "frees" the parent row for
deactivation, and *soft*-deactivating the parent never violates any FK
either way. Here the parent row is being **hard-deleted**, and Postgres will
enforce the FK regardless of the referencing user's `is_active` value — an
inactive user who never got reassigned off a role still holds a live foreign
key to it. Checking `is_active.is_(True)` only, the way Team/Department do,
would let an admin hard-delete a role that an inactive user still
references, and Postgres would reject the `DELETE` with a raw
`IntegrityError` (translating to an ugly `500`, not the clean `409` this
design intends) — or, worse, silently leave a dangling reference on SQLite
(no FK enforcement there), which is exactly the kind of silent-corruption
failure mode this project's other soft-delete designs go out of their way to
avoid. Checking *all* users regardless of `is_active` closes this
completely, at the cost of occasionally requiring an admin to reassign a
long-deactivated user's `role_id` before a role can be deleted — an
acceptable, rare inconvenience versus a raw 500 or silent corruption. I'm
confident enough in this reasoning to finalize it without a live db-admin
round-trip, but flagging the exact question and reasoning here per the
standing consult-before-finalizing rule, since it's directly the kind of FK/
constraint-behavior nuance db-admin owns — happy to have it double-checked
empirically against a real Postgres instance (per this project's own
"verified empirically, not assumed" precedent from the `AuditAction`
migration) before `DELETE /roles/{id}` ships.

### 6.4 Specific questions for db-admin on the new table (§6.2) — this section is now load-bearing, not optional

Unlike §6.3 above (a question I was comfortable reasoning through and
finalizing myself), **§6.2's table is a genuine new schema addition and
must get an explicit db-admin sign-off before it ships**, per this
project's standing rule. The exact proposed shape is written out in full in
§6.2 specifically so db-admin can review and build the migration from this
doc alone. Concrete questions:

1. **Indexing**: is `Index("role_id", "occurred_at")` (§6.2) sufficient for
   `GET /roles/{id}/audit`'s query shape (`WHERE role_id = :id ORDER BY
   occurred_at DESC`), or should `batch_id` also be indexed/included, given
   the read path groups rows by `batch_id` in application code after
   fetching them? My assumption is the single composite index is enough
   since the fetch is always `role_id`-scoped first and the per-`role_id`
   row count is inherently small (bounded by the catalog's 12 permission
   keys times however many times an admin edits one role) — but this is
   exactly the kind of query-shape call db-admin should confirm rather than
   me assuming.
2. **FK `ondelete` behavior**: `role_id`/`actor_id` have no explicit
   `ondelete` clause (matching this codebase's existing convention of never
   setting one). Given `role_id`'s FK is now load-bearing for §2.5's new
   409-if-has-history delete guard (i.e., the guard is the *only* thing
   preventing an orphaning hard-delete, not the DB constraint itself) — is
   relying purely on the application-level guard sufficient, or does
   db-admin want a real `ON DELETE RESTRICT` at the DB level too as a
   backstop against a future code path that hard-deletes a `Role` without
   going through this guard? I'd lean toward "the application guard is
   sufficient, consistent with how `delete_task`'s existing has-time-entries
   guard has no matching DB-level `ON DELETE RESTRICT` on `TimeEntry.
   task_id` either" — but flagging for confirmation since it's a real,
   decidable choice, not a settled convention.
3. **`change_type` as a plain `String`, not a native enum**: confirmed as
   the intended choice in §6.2's docstring, mirroring `RolePermission.
   permission_key`'s own precedent — is there any reason to prefer a native
   Postgres `ENUM` here instead, given the near-miss history that
   motivated avoiding one? I don't believe so (a plain string sidesteps
   `ALTER TYPE ... ADD VALUE` entirely, at the cost of no DB-level
   constraint on the two valid values — acceptable, matching
   `RolePermission.permission_key`'s already-accepted trade-off), but
   asking explicitly rather than assuming db-admin agrees.
4. **SQLite/Postgres parity**: does `Base.metadata.create_all` creating
   this new table need any dialect-specific handling at all (like `Team`'s
   `use_alter=True` circular-FK workaround elsewhere in `models.py`), or is
   a plain new table with two ordinary forward FKs (`roles.id`, `users.id`,
   both already-existing tables at the point this table is created)
   guaranteed conflict-free on both backends? My reading is the latter (no
   circular dependency, both target tables already exist), but this is
   squarely db-admin's call to verify empirically, not mine to assume,
   given this project's stated history with exactly this class of
   assumption-vs-verified-behavior gap.
5. **Migration for an already-deployed Postgres database**: confirm the
   plain `CREATE TABLE` (§6.2's closing paragraph) is the complete migration
   — i.e., that no existing table needs any accompanying change (it
   doesn't: `roles`/`users` are unmodified by this table's addition).

### 6.5 db-admin sign-off (finalized)

Reviewed §6.2's proposed shape against `backend/app/models.py` and
`backend/app/services/migrations.py` in full, and against this project's
"verified empirically, never assumed" standard (per the `AuditAction`
near-miss). **The model is implemented exactly as proposed in §6.2, with no
correction needed** — added to `backend/app/models.py` as
`RolePermissionAuditEntry`, immediately after `RolePermission`. Answers to
the five questions, each implemented (not just discussed):

1. **Indexing — confirmed sufficient, no change.** `Index("role_id",
   "occurred_at")` (composite, non-unique) matches `GET /roles/{id}/audit`'s
   query shape exactly (`WHERE role_id = :id ORDER BY occurred_at DESC`).
   `batch_id` does **not** need its own index: every read is `role_id`-scoped
   first, the per-role row count is small by construction (bounded by the
   12-key catalog times edit count for one role), and grouping by `batch_id`
   happens in application code after the indexed fetch, not as a second
   query. Not adding a speculative index here also matches this codebase's
   established "minimum actually needed, not defensive" indexing convention
   (see db-admin's own working-style note) — nothing in `routers/roles.py`
   as designed ever queries this table by `batch_id` or `actor_id` alone.

2. **FK `ondelete` — confirmed: no DB-level `ON DELETE RESTRICT`, matching
   convention.** Neither `role_id` nor `actor_id` gets an explicit
   `ondelete` clause, consistent with every other FK in `models.py` (none of
   them set one, including `TimeEntry.task_id` against `delete_task`'s own
   existing has-time-entries application-level guard — the precedent this
   design doc already cited). The application-level 409 guard in
   `DELETE /roles/{id}` (§2.5) is therefore the *only* thing preventing an
   orphaning hard-delete of a role with audit history; verified empirically
   (item 4 below) that omitting `ondelete` still means Postgres itself refuses
   the raw `DELETE` outright (`IntegrityError`, not a silent success) if that
   guard is ever bypassed — the FK is a real backstop at the DB level even
   without an explicit `ondelete` clause, it just requires the referencing
   rows to be dealt with first rather than cascading/nulling automatically.
   That fail-loud-by-default behavior is exactly what makes "rely on the
   application guard, no DB-level RESTRICT" an acceptable, not merely
   convenient, choice here.

3. **`change_type` as plain `String` — confirmed, no native enum.** Agreed
   with §6.2's own reasoning: mirrors `RolePermission.permission_key`'s
   already-accepted plain-string precedent, and avoids the exact
   `ALTER TYPE ... ADD VALUE` migration class this project already had one
   real near-miss with. No DB-level constraint on the two valid values is an
   acceptable trade-off, consistent with `permission_key` having none either.

4. **SQLite/Postgres parity — confirmed empirically, no dialect-specific
   handling needed.** Unlike `Team.manager_id` (which needs `use_alter=True`
   because of a genuine circular FK with `User.team_id`), this table has two
   ordinary *forward* FKs (`roles.id`, `users.id`), both already-existing
   tables at the point `Base.metadata.create_all` reaches this table — no
   circular dependency, nothing for SQLAlchemy's dependency-sort to trip on.
   Verified directly, not just reasoned: built the pre-B3 schema (`roles`/
   `role_permissions`/`users`, real rows, no `role_permission_audit_entries`
   table) on a real local Postgres 16 instance, ran `Base.metadata.create_all`
   + `ensure_schema_migrations` (this app's exact startup sequence), and
   confirmed the new table, its two FKs, and its composite index all exist
   with the expected shape — see
   `backend/tests/test_migration_role_permission_audit_new_table.py`. The
   full existing backend test suite (which builds this table via
   `Base.metadata.create_all` on a fresh in-memory SQLite engine for every
   test through `conftest.py::db_engine`) also passes unchanged, confirming
   SQLite-side parity too.

5. **Migration for an already-deployed Postgres database — confirmed: none
   needed, beyond `Base.metadata.create_all` itself.** This is a genuinely
   brand-new table with zero existing rows to backfill and no accompanying
   change to `roles`/`users` (both unmodified by this addition) — the same
   "no migration needed for a brand-new table" shape as
   `ManualTimeEntrySettings`, not the "new column/type change on an existing
   table" shape the rest of `services/migrations.py` exists for. **No new
   `_migrate_...` function was added to `services/migrations.py`** — a
   documentation-only note (item 9) was added to that module's own docstring
   recording this decision and pointing at this section and at the new test,
   so a future reader doesn't have to re-derive "why isn't B3 in here" from
   scratch. Verified empirically (not just asserted) via item 4 above: the
   *old*-shape database (pre-B3 tables/rows, no new table) reaches the
   *new*-shape database (new table present, usable) purely by running the
   app's existing two-call startup sequence unchanged — no third call, no
   manual operator step, satisfying this project's standing "every schema
   change must be automatic at startup" constraint without any new code in
   the migration module itself.

**§6.3 sanity check (requested, not blocking) — confirmed correct, with the
underlying FK behavior verified empirically, not just agreed with in
prose.** Built the exact scenario the reasoning describes on real Postgres
16: a custom role, a *deactivated* (`is_active=False`) user still holding
`role_id` pointed at it, and attempted a raw `DELETE FROM roles WHERE id =
:id` bypassing the application guard entirely. Result: Postgres raises
`IntegrityError` (`violates foreign key constraint`), exactly as
solution-architect predicted — not a silent no-op, not a clean success, and
not something SQLite would ever catch (no FK enforcement there at all). This
confirms an occupancy guard that checks only `is_active.is_(True)` users
(the Team/Department pattern) would let an admin's `DELETE /roles/{id}` call
reach this exact `IntegrityError` for a role an inactive user still
references, surfacing as an unhandled `500` instead of the intended `409` —
**§6.3's "check all users, active and inactive" divergence from the
Team/Department pattern is correct and should ship as designed, no
change.** Also verified the same fail-loud behavior holds for this round's
own new FK: attempting to hard-delete a role that still has
`RolePermissionAuditEntry` rows (bypassing §2.5's own new has-history 409
guard) also raises `IntegrityError` on Postgres, for the identical reason —
one more confirmation that the application-level guards in §2.5 are backed
by a real, enforced DB-level constraint underneath, not merely a
best-effort application convention.

See `backend/tests/test_migration_role_permission_audit_new_table.py` for
the executable proof of every claim in this section (table shape, FK
targets, index shape, real inserts/reads against real pre-existing `Role`/
`User` rows, idempotency of a second `create_all` + `ensure_schema_migrations`
pass, and both `IntegrityError` cases above) — run against a real local
Postgres 16 instance
(`postgresql://app_user:app_password@localhost:5432/time_tracking`), not
just SQLite, per this project's standing verification rule.

**Nothing in this section blocks fullstack-dev-1** — the model is in
`backend/app/models.py`, no further migration code is needed, and both
occupancy-guard behaviors (role-level and audit-history-level) are confirmed
safe to build against as specified in §2.5.

---

## 7. Summary for hand-off

### For `db-admin`
**Now a real, non-empty ask — §6.1 corrects the original "nothing to
build" conclusion.** Review and build the migration for the one new table
in §6.2 (`role_permission_audit_entries`), and answer the five specific
questions in §6.4. §6.3's reasoning (role-deletion occupancy guard checking
inactive users too) is a lower-priority sanity check, not blocking, exactly
as originally flagged.

### For `fullstack-dev-1` (backend) — updated for both finalized decisions
1. `models.py`: new `Permission(str, enum.Enum)` with the 12 keys in §1.3
   (alongside `Role`/`RolePermission`, not a column type); new
   `RolePermissionAuditEntry` table (§6.2, once db-admin signs off per §6.4).
2. `services/authz.py`: `has_permission(user, permission)` (§3); the new
   additive branch in `can_view_task` (§1.4.1, exact code given there —
   append last, after every existing branch); the new
   `can_control_time_entry`/`assert_can_control_time_entry` functions
   (§1.4.3). **`can_edit_task` itself is not modified anywhere in this
   round** — confirm this explicitly in review, since it's the one function
   where a naive "mirror `can_view_task`'s change" would be wrong (§1.4.2).
3. `services/users.py`: `resolve_role_assignment(...)` (§4.2), replacing
   direct `role_id_for_builtin_role` calls in `routers/users.py`; new
   `validate_role_id(db, role_id)` existence check.
4. New `services/roles.py`: `record_permission_change(...)` (§6.2) — the
   before/after diff + `RolePermissionAuditEntry` writer, called from
   `PUT /roles/{id}/permissions` only when the diff is non-empty (§2.4).
5. New `backend/app/routers/roles.py`: `GET/POST/PATCH /roles`,
   `PUT /roles/{id}/permissions`, `DELETE /roles/{id}` (now with the
   additional has-audit-history 409 guard, §2.5), `GET /roles/{id}/audit`
   (§2.7) — all per §2. Slug generation for `key` on create (§2.2).
6. `routers/time_entries.py`: `_get_owned_entry` (exact replacement code in
   §1.4.3); `pause_timer`/`resume_timer`/`stop_timer` swap their
   `assert_can_edit_task(current_user, entry.task)` call for
   `assert_can_control_time_entry(current_user, entry)` (§1.4.3) —
   `update_task`/`delete_task` in `tasks.py` are **not** touched.
7. `schemas.py`: `RoleRead`/`RoleCreate`/`RoleUpdate`/
   `RolePermissionsUpdate`/`RolePermissionHistoryEntry` (new);
   `UserCreate.role_id`, `UserUpdate.role_id`, `UserRead.role_id`/
   `role_name`, `UserRead.role` → `UserRole | None` (§4.1, §4.4 — this last
   one is a required bug fix, not optional).
8. Convert the specific call sites listed in §3.1's table from
   `assert_admin`/`role_key(...) == "admin"` to `has_permission(...)`.
   Leave every call site in §3.2 untouched.
9. `routers/notifications.py`: the direct-reports-structural fix in §1.6,
   bundled with `view_all_reminders`'s wiring.
10. Tests: every existing test asserting `assert_admin`-style 403s on the
    converted endpoints (§3.1) for a non-admin still needs to pass for a
    *plain* employee/manager (who has no `RolePermission` rows and isn't
    floor-admin) — `has_permission` returns `False` for them exactly like
    `role_key(...) == "admin"` did, so this should be behavior-preserving:
    worth a regression pass across `test_authorization_and_guards.py`.
    New coverage needed for §1.4's escalation boundary specifically: a
    custom role holding only `view_all_tasks` must get `200` on
    `GET /tasks/{id}` for a task it doesn't own, but `403` on
    `PATCH`/`DELETE /tasks/{id}` for that same task — and a role holding
    only `view_all_time_entries` must be able to `pause`/`resume`/`stop`
    another user's entry but still get `403` `PATCH`-ing that entry's task.

### For `fullstack-dev-2` (frontend wiring) and `designer`
1. New `frontend/src/app/admin/roles/page.tsx` + `RoleFormPanel` +
   `RolePermissionsPanel` + a "History" panel (§5.1) — SlideOver-based,
   matching `departments`/`teams`/`admin/users` conventions exactly.
2. `frontend/src/app/admin/users/page.tsx` + `UserFormPanel`: switch the
   role column/picker from `u.role`/fixed 3-value enum to `u.role_name`/
   `GET /roles`-sourced `role_id` picker (§5.2).
3. Data shape: `Role { id, key, name, is_builtin, permission_keys, created_at }`;
   `User` gains `role_id: string | null`, `role_name: string`, and `role:
   UserRole | null` (was non-optional); new `RolePermissionHistoryEntry {
   batch_id, occurred_at, actor: { id, full_name, email }, added: string[],
   removed: string[] }` from `GET /roles/{id}/audit` (§2.7).

### Decisions finalized this round (previously open questions)
1. **§1.4** (was open question 1): `can_view_task` is extended with an
   additive `has_permission()` branch; `can_edit_task` is deliberately left
   unchanged, with time-entry control handled by a new, separately-scoped
   `can_control_time_entry` function instead of a `can_edit_task` branch, so
   no view-labeled permission can escalate into edit/delete rights. Full
   reasoning and exact code in §1.4.1–§1.4.4.
2. **§2.4/§6** (was open question 2): a permission-change audit log is
   built now, not deferred — new `RolePermissionAuditEntry` table (§6.2),
   written by `PUT /roles/{id}/permissions` (§2.4), read via
   `GET /roles/{id}/audit` (§2.7), surfaced in the Roles admin screen via a
   "History" panel (§5.1). This flips §6.1's original "no migration needed"
   conclusion — a real migration is now required and needs db-admin
   sign-off per §6.4 before it ships.

No open questions remain from the original draft. Any new ones arising from
db-admin's review of §6.4 will surface through that review, not here.
