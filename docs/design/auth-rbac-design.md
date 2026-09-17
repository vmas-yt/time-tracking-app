# Authentication & RBAC Overhaul — Design Document

Status: draft for backend-dev + designer hand-off (design only, nothing here
is implemented)
Owner: solution architect
Source of truth: `docs/PRD.md`
Reviewed against: `backend/app/models.py`, `backend/app/schemas.py`,
`backend/app/deps.py`, `backend/app/core/config.py`, `backend/app/core/security.py`,
`backend/app/main.py`, `backend/app/routers/auth.py`, `routers/users.py`,
`routers/tasks.py`, `routers/time_entries.py`, `routers/admin.py`,
`routers/reports.py`, `routers/notifications.py`, `routers/projects.py`,
`services/authz.py`, `services/tasks.py`, `services/timer.py`,
`backend/tests/conftest.py`, `backend/tests/test_authorization_and_guards.py`,
`frontend/src/app/login/page.tsx`, `frontend/src/app/layout.tsx`,
`frontend/src/app/page.tsx`, `frontend/src/app/board/*`,
`frontend/src/app/reports/page.tsx`, `frontend/src/app/admin/page.tsx`,
`frontend/src/app/tasks/[id]/page.tsx`, `frontend/src/components/NavBar.tsx`,
`frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`,
`frontend/src/board/session.ts`, `render.yaml`.

Same conventions as `docs/design/kanban-timer-design.md`: **CONFIRMED** means
current backend behavior already matches the target and needs no rework;
**GAP** flags a real problem in the current code; **PROPOSED CHANGE** is a new
rule/endpoint/column being introduced by this design. A lot of the
authorization groundwork already exists from the "harden task/timer backend"
work — this doc reuses it rather than re-deriving it, and is explicit about
what's new versus already shipped.

---

## 1. What's changing, at a glance

1. Delete `POST /auth/register` and the first-user-becomes-admin bootstrap.
   Only an admin can create accounts from now on.
2. A new startup-time seeding mechanism creates exactly one admin account in
   a brand-new deployment, since self-registration can no longer do it.
3. Every frontend route gets a real auth guard (redirect-to-login), not just
   inline error text after a failed fetch.
4. New admin-only user-management endpoints: create user, edit user, reset
   password, deactivate ("delete") user, plus tightened validation on the
   existing `manager_id` field.
5. A full route-by-route audit of role enforcement, closing gaps found in
   `time-entries` (no admin override, timer-start misattribution),
   `reports` (no visibility scoping at all), and `projects` (no role gate).
6. Frontend "Add Task" becomes a button + slide-over. **Confirmed no backend
   contract change is needed for this** — `POST /tasks` already accepts
   exactly the fields the inline form sends today (see `TaskCreate` in
   `schemas.py` and `NewTaskForm.tsx`); the slide-over is a pure presentation
   change around the same `board.createTask(...)` call.

---

## 2. Data model changes

### 2.1 `User` — add two columns (PROPOSED CHANGE)

```
User (users)
  ... existing fields unchanged ...
  is_active: bool, default True, not null            [NEW]
  deactivated_at: datetime | null                    [NEW]
```

No other model changes. `manager_id` already exists on `User` — it needs
better validation and a dedicated admin UI, not a schema change (§6).

Why these two columns and nothing more (e.g. no `must_change_password`, no
`UserAuditEntry`): kept to the minimum needed to make "delete a user" safe
(§4) and to let login/`get_current_user` reject a deactivated account
immediately. A forced-password-change-on-first-login flag and a
user-management audit log (mirroring `TaskAuditEntry`) are both reasonable
future asks but have no PRD basis and aren't required to close the gaps in
this request — flagged as **OPEN QUESTIONS** at the end rather than built.

### 2.2 Migration note

This project has no Alembic migrations wired up (`Base.metadata.create_all`
in `main.py`'s `lifespan` is the only schema-creation path, confirmed — no
`alembic/` directory under version control despite the package being
installed transitively). `create_all` only creates *missing tables*, it does
not `ALTER TABLE` an existing one to add a column. That means:

- **Fresh SQLite dev DB / fresh Postgres on Render**: no action needed,
  `create_all` creates `users` with the new columns from a clean slate.
- **An already-deployed Postgres database** (if this ships after the app has
  real users in it): `create_all` will silently leave `is_active`/
  `deactivated_at` missing and every `INSERT`/`SELECT` referencing them will
  fail at runtime. **This needs an explicit one-time migration** (`ALTER
  TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE, ADD COLUMN
  deactivated_at TIMESTAMP NULL`) run before the new backend code is
  deployed. Flagging this now since it's easy to miss with no migration
  tooling in place — backend-dev should run it by hand against the Render
  Postgres instance (or introduce Alembic properly) as part of this change,
  not treat `create_all` as sufficient.

---

## 3. Bootstrapping the first admin

### 3.1 The problem

Today, `POST /auth/register` is public and the first row ever inserted into
`users` becomes admin (`routers/auth.py`). Once self-registration is deleted,
nothing can ever insert the first `User` row — a brand-new deployment has an
empty `users` table and zero way to log in, ever, through the API.

### 3.2 Options considered

| Option | How it'd work | Pros | Cons |
|---|---|---|---|
| A. Env-var-driven seed on startup | `lifespan()` checks `users` table; if empty and `BOOTSTRAP_ADMIN_EMAIL`/`BOOTSTRAP_ADMIN_PASSWORD` are set, inserts one admin row | Fits the app's existing pattern exactly — `Settings` (`core/config.py`) already reads env vars for `secret_key`/`cors_extra_origin_host`, and `render.yaml` already uses `generateValue: true` for `SECRET_KEY`; runs automatically on every deploy with zero extra operator steps beyond setting two env vars once; idempotent (only fires when the table is empty) | Password sits in an env var indefinitely unless rotated after first login (see §3.5) |
| B. One-time seed script run manually (`python -m app.scripts.seed_admin`) | Operator SSHes in or runs a one-off shell command post-deploy | Doesn't require restarting the web process with secrets in its env | Render's free-tier web services (`render.yaml` plan: free) don't expose a `preDeployCommand`/shell hook, so this would need a manual `render shell` session every time a fresh environment is stood up — worse operator ergonomics than A, and there's no existing precedent for a scripts/ dir or CLI entrypoint in this codebase to extend |
| C. Manual DB insert (docs tell the operator to `INSERT INTO users ...` by hand with a pre-hashed password) | No code at all | Zero code | Requires the operator to hand-compute a bcrypt hash outside the app; error-prone, unfriendly, and out of step with everything else in this app being API/env-var driven |
| D. Special unauthenticated "claim admin" endpoint, usable exactly once | `POST /auth/claim-admin` works only while `users` table is empty | No env var needed | Reintroduces an unauthenticated account-creation endpoint — exactly the attack surface item 1 is trying to remove (a small race window between deploy and the admin's first visit is publicly exploitable); rejected on that basis alone |

### 3.3 Chosen approach: A, env-var-driven startup seed

**Justification**: it fits the codebase's existing conventions (pydantic
`Settings` + `render.yaml` env vars) more closely than any alternative,
requires no new script/CLI convention, needs zero manual steps beyond
setting two Render env vars once, is naturally idempotent, and — critically —
does not reopen an unauthenticated write path (rejecting D).

### 3.4 Design

New settings (`app/core/config.py`):

```python
bootstrap_admin_email: str | None = None
bootstrap_admin_password: str | None = None
bootstrap_admin_name: str = "Admin"
```

New function, `app/services/bootstrap.py::ensure_bootstrap_admin(db: Session) -> None`:

- If `db.query(User).count() > 0`: return immediately (never touches a
  non-empty table — this is not a "reset" or "ensure an admin always exists"
  routine, only a one-time cold-start seed).
- Else, if `settings.bootstrap_admin_email` and `...password` are both set:
  insert one `User(email=..., full_name=settings.bootstrap_admin_name,
  hashed_password=hash_password(...), role=UserRole.ADMIN, is_active=True)`,
  commit, and log (stdout) `"Bootstrap admin created: <email>"` — never log
  the password.
- Else (table empty, env vars unset): log a startup warning: `"No users
  exist and BOOTSTRAP_ADMIN_EMAIL/BOOTSTRAP_ADMIN_PASSWORD are not set — no
  one can log in. Set both and restart the service."` and continue booting
  (don't crash the app over this — health checks still need to pass).

Wired into `app/main.py`'s existing `lifespan`, immediately after
`Base.metadata.create_all(bind=engine)`, using a short-lived `Session` from
the same `sessionmaker` the app already uses via `get_db`.

`render.yaml` changes (both on the backend service's `envVars`):

```yaml
- key: BOOTSTRAP_ADMIN_EMAIL
  value: admin@yourcompany.example   # operator sets this to a real address
- key: BOOTSTRAP_ADMIN_PASSWORD
  generateValue: true                # Render generates and stores a random secret
```

This mirrors the existing `SECRET_KEY: generateValue: true` line exactly.
The operator reads the generated password from the Render dashboard once,
logs in, and (see §3.5) should immediately rotate it.

### 3.5 Local dev / disaster recovery

A thin CLI, `python -m app.scripts.seed_admin`, sharing `ensure_bootstrap_admin`
under the hood, for two cases the startup hook doesn't cover:
1. **Local dev** without wanting to set env vars for a throwaway SQLite DB —
   the script can prompt for email/password interactively.
2. **Lockout recovery** — every admin account got deactivated (see the
   last-admin guard in §6.4, which should make this unreachable in normal
   operation, but a direct DB edit or `--force` flag on this script is the
   documented recovery path if it ever happens) rather than "reinstate
   self-registration," which item 1 explicitly forbids.

This is a secondary/optional convenience, not the primary bootstrap
mechanism — flagging it so backend-dev knows it's small in scope (a few
lines reusing existing `hash_password`), not a new subsystem.

### 3.6 Residual risk (explicit, not silently accepted)

The bootstrap password is a static env var with no forced rotation. Since
this design deliberately does not add a `must_change_password` flag (§2.1),
nothing *technically* forces the operator to change it after first login.
**Operational mitigation, not a code control**: document in the runbook that
the first action after logging in with the bootstrap credentials is to call
the new `PATCH /users/me/password` (§5.4) to set a real password only the
operator knows. Flagged as an **OPEN QUESTION** for the PM: if this needs to
be enforced rather than merely documented, add `User.must_change_password`
and a login-response flag the frontend redirects on — not built here to
avoid scope creep on a single-admin internal tool.

---

## 4. Removing self-registration and gating login

### 4.1 Backend

- **Delete** `POST /auth/register` from `routers/auth.py` entirely (the
  handler, the "first user becomes admin" comment/logic, and the route). Any
  request to it becomes a generic `404` (route no longer exists) — this is
  the explicit, intentional breaking change item 1 asked for.
- `POST /auth/login` stays public (unavoidably — it's how anyone gets a
  token) but gets one new check: **PROPOSED CHANGE** — reject login for a
  deactivated account:
  ```
  if not user.is_active:
      403 {"detail": "This account has been deactivated. Contact your administrator."}
  ```
  (403, not 401 — this is intentionally distinguishable from "wrong
  password." Internal ops tool, small trusted user base, no meaningful
  account-enumeration threat model; being explicit is more operator-friendly
  than generic obscurity here.)
- `app/deps.py::get_current_user` gets the same check added — **PROPOSED
  CHANGE**, and the important one: JWTs are stateless and live for
  `access_token_expire_minutes` (24h by default). Without this check, an
  admin deactivating someone only stops *future logins*; the deactivated
  user's already-issued token keeps working for up to 24h. Add:
  ```
  if not user.is_active:
      raise credentials_exception   # 401, same shape as an invalid token
  ```
  This makes deactivation take effect on the deactivated user's very next
  request, not at their token's natural expiry.

### 4.2 Backend route-auth audit (item 4's "confirm what's already enforced")

Every router already depends on `get_current_user` except:
- `POST /auth/login` — must stay open (how else would anyone get a token).
- `GET /health` — CONFIRMED fine to stay open; it's a liveness probe with no
  user data, standard convention, not part of "every page/action" scope.
- `POST /auth/register` — being deleted (§4.1).

**CONFIRMED**: no other endpoint across `tasks.py`, `time_entries.py`,
`admin.py`, `reports.py`, `notifications.py`, `projects.py`, `users.py` is
missing the `current_user: User = Depends(get_current_user)` parameter. So
"every API call requires a valid token" is **already true** at the
transport/dependency level today. The real gap (item 2's "pages render
regardless of login state") is entirely on the **frontend** — see §8.

---

## 5. Admin user-management API

All five endpoints below live in `routers/users.py` (existing router,
`prefix="/users"`).

### 5.1 `POST /users` — create a user (**NEW**, admin only)

Request:
```json
{
  "email": "new.hire@company.com",
  "full_name": "New Hire",
  "role": "employee",
  "manager_id": "uuid|null",
  "password": "temporary-password-here"
}
```
- `role` optional, defaults to `"employee"` (mirrors `TaskType`'s
  default-value pattern in `TaskBase`).
- `manager_id` optional (nullable), validated per §6.5.
- `password` **required** — the admin sets the initial credential directly
  (see §5.5 for why, versus server-generating one).

Response: `201` → `UserRead` (existing shape, unchanged: `id, email,
full_name, role, manager_id, created_at`, **plus the new `is_active`
field**, see §5.6).

Errors:
- `400` — email already registered (same message/status as the old
  `/auth/register` used, for consistency: `"Email already registered"`).
- `400` — `manager_id` doesn't reference an existing user, references an
  inactive user, or references a user whose `role == "employee"` (§6.5).
- `403` — caller isn't admin.
- `422` — missing `email`/`full_name`/`password`, malformed email
  (`EmailStr` already handles this), or `password` shorter than 8 chars
  (**PROPOSED CHANGE** — no minimum length exists anywhere today, including
  the old register endpoint; add `Field(min_length=8)` to the password field
  used here and in §5.4/§5.5).

### 5.2 `PATCH /users/{id}` — edit a user (extends existing endpoint)

Currently `UserUpdate` only allows `role`/`manager_id` (already admin-gated
via `assert_admin` — **CONFIRMED, no change to the gate itself**). Extend the
schema:

```python
class UserUpdate(BaseModel):
    full_name: str | None = None      # NEW
    email: EmailStr | None = None     # NEW
    role: UserRole | None = None      # existing
    manager_id: str | None = None     # existing
    is_active: bool | None = None     # NEW — see §6.6 (reactivation path)
```

Errors (in addition to existing `404` task-not-found-style `404` user):
- `400` — new `email` collides with another user's email.
- `400` — `manager_id` fails the same validation as §5.1/§6.5.
- `409` — attempting to set `is_active: false` here on the sole remaining
  admin (§6.4) — actually routed through `DELETE` normally, see §5.4; this
  schema-level path is only relevant if the frontend chooses to toggle
  `is_active` via `PATCH` instead of hitting `DELETE` directly. Both paths
  must share the same guard (recommend a single `deactivate_user(db, user)`
  service function used by both routes rather than duplicating the check).

### 5.3 `POST /users/{id}/reset-password` — admin sets a new password (**NEW**, admin only)

Request: `{ "new_password": "new-temp-password" }` (same `min_length=8`
rule).
Response: `204 No Content`.
Errors: `403` not admin, `404` user not found, `422` password too short.

This is the mechanism for "admin resets a forgotten/compromised password for
an existing user" — distinct from `PATCH /users/me/password` (§5.4), which
is the self-service path.

### 5.4 `PATCH /users/me/password` — self-service password change (**NEW**, any authenticated user)

Not explicitly requested in the brief, but a necessary complement to §5.1/
§5.3: an admin-set password is only useful if the user can subsequently
change it to something only they know, and this is also exactly how an
operator rotates the bootstrap admin password per §3.6.

Request: `{ "current_password": "...", "new_password": "..." }`.
Response: `204 No Content`.
Errors: `401` `current_password` doesn't match (reuse `verify_password`),
`422` `new_password` too short.

### 5.5 Why "admin sets the password directly," not "system generates and displays once"

Both were considered per the brief's explicit either/or. Chosen: **admin
sets it directly**.

- Matches an existing pattern already in the codebase: `UserCreate.password:
  str` (in `schemas.py`) already exists as a plain admin/user-supplied field
  — reusing that shape for `POST /users` is the smallest change, versus
  inventing new generation/entropy/display-once UI machinery that doesn't
  exist anywhere in this app.
- The generate-and-display-once pattern needs additional frontend surface
  (a "copy this now, it will never be shown again" modal) purely to solve a
  problem (secure delivery) that doesn't really exist here: this is an
  internal Operations tool with a small number of admins who already have a
  side channel (Slack/in person) to hand a new hire their temp password —
  the PRD's explicit non-goal of "no integrations with external systems"
  cuts against building an email-delivery flow to solve this "nicely."
- Trade-off, called out rather than hidden: the password briefly exists in
  the `POST /users`/`reset-password` request body. Standard mitigation
  (HTTPS everywhere, which `render.yaml`'s services already run under) plus
  §5.4 makes the admin-set password short-lived by design (recommend as
  operator process, not enforced in code — see the `must_change_password`
  open question in §2.1).

### 5.6 `DELETE /users/{id}` — deactivate a user

Covered fully in §6 (it's the biggest design decision in this doc, given its
own section).

### 5.7 `GET /users` — extend existing endpoint (**PROPOSED CHANGE**, filtering only)

Currently returns every user to every authenticated caller, no filtering —
**CONFIRMED that visibility scope itself is fine to keep** (the assignee/
manager pickers on the board and task-detail pages need the full list, for
every role, and the brief doesn't ask to restrict who can see the user
directory). The one change: exclude deactivated users by default so they
stop appearing in assignee/manager pickers.

```
GET /users?include_inactive=true
```
- Default (`include_inactive` absent/false): `WHERE is_active = true`.
- `include_inactive=true`: **admin only** — returns everyone, including
  deactivated accounts (needed for the admin screen that lists/reactivates
  them, §6.6). Non-admins passing this param have it silently ignored
  (treated as false) rather than erroring — keeps the endpoint simple for
  the common picker use case while not exposing a new 403 surface for a
  cosmetic filter.

`UserRead` gains the new field:
```json
{
  "id": "uuid", "email": "...", "full_name": "...",
  "role": "employee|manager|admin",
  "manager_id": "uuid|null",
  "is_active": true,
  "created_at": "iso8601"
}
```

---

## 6. User deletion strategy — soft-delete via `is_active`

### 6.1 The problem, restated precisely

A `User` row is referenced by: `Task.assignee_id`, `Task.created_by_id`,
`TimeEntry.user_id`, `TaskComment.author_id`, `TaskAuditEntry.actor_id`,
`TaskStatusEvent.changed_by_id`, and `User.manager_id` (self-referential).
None of these foreign keys are declared with `ondelete="CASCADE"` in
`models.py`. That means a true `DELETE FROM users WHERE id = ...` would, on
Postgres, fail with an FK violation the moment the user has any history at
all (which is the common case, not the edge case, for a real employee) —
and on SQLite (where FK enforcement is off by default and nothing in
`database.py` turns it on), it would silently succeed and leave every one of
those child rows pointing at a nonexistent user id, corrupting the audit
trail and every report that joins through it.

### 6.2 Options considered

| Option | Effect | Verdict |
|---|---|---|
| Hard delete, cascade to children | Deletes the user and every `Task`/`TimeEntry`/`TaskComment`/`TaskAuditEntry`/`TaskStatusEvent` they ever touched | **Rejected** — silently destroys the audit trail and reporting history for potentially hundreds of tasks the moment one departed employee is removed; directly contradicts the PRD's "audit trail — required" and undermines cycle-time/throughput/CFD numbers exactly like the kanban-timer doc's task-delete GAP (§1.2 there) already warned against for a single task, at far larger blast radius |
| Hard delete, blocked if referenced (mirror the existing task-delete guard) | `DELETE /users/{id}` returns `409` if the user has any Task/TimeEntry/Comment/AuditEntry/StatusEvent row, or is anyone's `manager_id` | **Rejected** — unlike a brand-new task (which is genuinely deletable most of the time), a real employee who's used the system at all will almost always have *some* history, so this option would make "delete a user" effectively permanently unusable — not a real answer to "an employee left the company," which is the actual use case an admin needs this for |
| Reassign all their data to another user, then hard delete | Bulk-`UPDATE` every FK to point at a chosen replacement user, then delete | **Rejected** — falsifies the audit trail (rewrites *who actually did what*) and is exactly the kind of silent history-rewrite the audit trail exists to prevent; also a much bigger, riskier bulk-write operation for what should be a routine "employee left" action |
| **Soft-delete / deactivate (`is_active=false`)** | User row and all history untouched; account can no longer log in or receive new work | **Chosen** |

### 6.3 Why soft-delete, tied back to the PRD and existing patterns

- Preserves every historical `Task`/`TimeEntry`/`TaskComment`/
  `TaskAuditEntry`/`TaskStatusEvent` exactly as recorded — required by the
  PRD's audit trail and by the reporting endpoints, which are all derived
  from this data (`docs/design/kanban-timer-design.md` §1.2 already
  establishes this "never silently lose history" principle for tasks; this
  extends the same principle to users).
- It's the same shape of decision the existing task-delete guard already
  made (block/preserve data rather than cascade), just resolved as
  deactivate-instead-of-block here because, unlike tasks, blocking outright
  isn't a workable answer for "an employee left."
- Minimal schema footprint: one boolean + one timestamp, no new tables.

### 6.4 `DELETE /users/{id}` — exact behavior (**PROPOSED CHANGE**, this is a new endpoint — none exists today)

Admin only. Despite the `DELETE` verb (kept for REST-conventional client
ergonomics — the frontend just calls `DELETE`), this **does not remove the
row**. It:

1. `404` if no such user.
2. `409` if `user.role == "admin"` and it is the **only** currently-active
   admin (`SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=true`
   `== 1` and this is that one). **Why**: self-registration is gone (item
   1), so if the last admin is deactivated, *nothing* can ever create another
   admin again short of the disaster-recovery script in §3.5 — this guard
   makes that unreachable in normal operation. Detail message: `"Cannot
   deactivate the only remaining admin account."`
3. Otherwise: sets `is_active = False`, `deactivated_at = now()`, commits.
4. **Side effect — auto-pause open timers** (mirrors the existing "manual
   On-Hold auto-pauses the timer" pattern in `services/tasks.py::change_status`):
   for every `TimeEntry` belonging to this user with `status == RUNNING`,
   call the existing `pause_entry()` helper and record a
   `TaskAuditEntry(action=TIMER_PAUSED, detail="Timer auto-paused (user
   deactivated)")`. Entries already `PAUSED` are left as-is (nothing to do —
   they're not actively running against anyone). **Why not auto-stop
   instead**: stopping would force the task to `Completed`, which may be
   false — the work genuinely isn't done just because the person who was
   doing it left; pausing is the accurate representation and matches how a
   manual On-Hold is already handled elsewhere in the app.
5. Response: `200` → `UserRead` (with `is_active: false`), not `204` — the
   frontend needs the updated record to grey the row out in place rather
   than remove it from a list (an admin user-management screen should show
   deactivated accounts, not make them vanish).

### 6.5 Effects of deactivation on other endpoints

| Area | Behavior |
|---|---|
| Login | `403` "account deactivated" (§4.1) |
| Existing token | Rejected on next request via `get_current_user` (§4.1) |
| `GET /users` (default) | Excluded (§5.7); still visible with `include_inactive=true` |
| `POST /tasks` / `PATCH /tasks/{id}` — `assignee_id` | **PROPOSED CHANGE**: reject (`400`) assigning a task to an inactive user. No such validation exists today (any string is accepted as `assignee_id` with no existence check at all, in fact — see §7.1 for that broader gap) |
| `PATCH /users/{id}` — `manager_id` | **PROPOSED CHANGE**: reject (`400`) setting a `manager_id` to an inactive user (§6.6/§7) |
| Existing `Task`/`TimeEntry`/`TaskComment`/`TaskAuditEntry`/`TaskStatusEvent` rows referencing this user | Untouched — ids and historical attribution stay exactly as recorded |
| Reports / audit trail | Continue to resolve the deactivated user's name via `GET /users/{id}` or the `include_inactive=true` list — **not** filtered out of historical views, only out of forward-looking pickers |
| Someone whose `manager_id` points at the now-deactivated user | **Not automatically reassigned.** They keep reporting (structurally) to a manager who can no longer log in. This is a deliberate non-decision — flagged as an **OPEN QUESTION** below, not silently resolved |

**OPEN QUESTION** (flagging rather than deciding, per the instructions,
since the PRD is silent and there's no clearly-better default): should
deactivating a manager force a bulk reassignment prompt for their direct
reports? Proposed default if a decision is needed now: no automatic
reassignment; the `DELETE` response (§6.4) should additionally include a
`reports_affected: number` count (query `users WHERE manager_id = :id AND
is_active = true`) so the admin sees the impact and can follow up with
individual `PATCH /users/{report_id}` calls — a "confirm you understand the
blast radius" signal without an automated bulk mutation.

### 6.6 Reactivation

`PATCH /users/{id}` with `{"is_active": true}` (admin only, §5.2) clears
`deactivated_at` and restores login. No separate endpoint needed — this is
exactly the kind of field-level edit `PATCH /users/{id}` already exists for.

---

## 7. `manager_id` assignment — validation and admin UI data shape

### 7.1 Current state (confirmed gap)

`manager_id` already exists on `User` (`models.py`) and is already editable
via admin-gated `PATCH /users/{id}` (**CONFIRMED** — the gate itself is
fine). But **there is currently zero validation on the value**: any string
is accepted, including a nonexistent user id, the user's own id (a
self-referential loop), or another employee's id regardless of that
employee's `role`. There's also no dedicated "assign manager" UI today — the
admin screen (`frontend/src/app/admin/page.tsx`) inlines a `<Select>` of
every other user per row, which is close to what's needed but needs the new
validation to have real API-level teeth (today the frontend `<Select>`
happens to only ever submit valid ids because it's populated from the same
user list, but a raw API caller could submit garbage).

### 7.2 New validation rules (**PROPOSED CHANGE**), applied in both `POST /users` and `PATCH /users/{id}`

| Rule | Status code | Detail |
|---|---|---|
| `manager_id` references a user that doesn't exist | `400` | `"manager_id does not reference an existing user"` |
| `manager_id` references an inactive user | `400` | `"Cannot assign a deactivated user as a manager"` |
| `manager_id == user.id` (self-reference) | `400` | `"A user cannot be their own manager"` |
| `manager_id` references a user whose `role == "employee"` | `400` | `"manager_id must reference a user with role 'manager' or 'admin'"` |

The last rule is a new server-side constraint, worth calling out
specifically: **CONFIRMED existing behavior today** is that `manager_id` and
`role` are completely orthogonal in `services/authz.py` —
`can_view_task`/`can_edit_task` check `task.assignee.manager_id ==
current_user.id` with no check at all on the current user's own `role`.
Practically, that means today an admin *could* set a plain `employee`'s id
as someone's `manager_id` and that employee would silently gain
task/time-viewing rights over a report they have no business role
justifying. This design keeps the *authz check* exactly as-is (§8 — it's
correct and doesn't need to change) but adds the *input validation* so the
data that feeds it can't produce that confusing state in the first place.

Not recursive: this is a single-level check only (no cycle detection beyond
direct self-reference, e.g. A→B→A is not currently prevented). Flagged as an
**OPEN QUESTION** — low priority, since the org chart in this app is small
and admin-managed by hand; a full cycle-detection pass is easy to add later
(walk `manager_id` up to some depth limit) if it becomes a real problem, not
built now to avoid scope creep on a low-likelihood input.

### 7.3 Data shape for the designer

A dedicated "Manager" column/picker (already sketched in `admin/page.tsx`)
should be populated from `GET /users?include_inactive=false` **filtered
client-side (or via a new optional `role` query param, designer's choice) to
`role in {manager, admin}`** — i.e., the picker itself should only ever
offer valid choices, matching the server-side rule in §7.2 so the UI never
round-trips a doomed request. No new endpoint needed for this; either extend
`GET /users` with an optional `role` filter param (small, backward
compatible) or filter the existing full list in the browser — designer's
call, both satisfy the same data need.

---

## 8. Frontend: full login gating

### 8.1 The problem, precisely

Confirmed by reading the pages: `frontend/src/app/page.tsx` (Projects home),
`frontend/src/app/reports/page.tsx`, `frontend/src/app/board/page.tsx` →
`BoardScreen.tsx`, and `frontend/src/app/tasks/[id]/page.tsx` **all** render
their full page shell and unconditionally fire `useEffect`-driven API calls
on mount (`api.listProjects()`, `api.reportCycleTime()`, etc.) regardless of
whether a token exists in `localStorage`. `frontend/src/app/admin/page.tsx`
is the one partial exception — it fetches `api.me()` and conditionally
renders an "Admin access required" message if the caller isn't an admin —
but it still does this *after* rendering (a loading state, then the message)
rather than redirecting, and it doesn't handle "no token at all" any
differently from "logged in as non-admin." None of the pages redirect
unauthenticated visitors to `/login`; they show inline red error banners
("log in first at /login") next to an otherwise-empty/broken page shell.
`NavBar.tsx` always renders a static "Log in" link regardless of session
state (doesn't reflect being logged in at all, doesn't show current
user/logout).

The backend is not the problem here (§4.2 — already 401s everything). This
is purely a frontend UX/routing gap.

### 8.2 Design: a layout-level `AuthGate` + shared `AuthContext`

New files (naming for backend-dev/designer alignment, not prescriptive):

- `frontend/src/lib/auth.tsx` — `AuthProvider` (client component) +
  `useAuth()` hook. On mount: read `localStorage.getItem("token")`.
  - No token → `authState = "anonymous"`.
  - Token present → call `api.me()`. Success → `authState = "authenticated"`,
    store the resolved `User` (including the new `is_active`/`role`) in
    context. Failure (401, including the deactivated-account case from
    §4.1) → clear `localStorage`, `authState = "anonymous"`.
  - Exposes `{ user: User | null, authState: "loading"|"anonymous"|"authenticated", logout(): void }`.
  - This **replaces** the ad hoc `api.me()` calls duplicated today in
    `NavBar.tsx`, `admin/page.tsx`, and `board/session.ts`'s
    `useTimerSession` — all three should read from this one context instead,
    so there's a single source of truth for "who is logged in" and a single
    place the redirect logic lives. (Not strictly required to close the auth
    gap, but called out because leaving three independent `api.me()` calls
    in place after adding a fourth in the gate is an obvious inconsistency a
    reviewer would flag — designer/backend-dev should consolidate while
    they're in this code.)

- `frontend/src/components/AuthGate.tsx` — client component, wraps
  `{children}` inside `AuthProvider`. Behavior:
  - While `authState === "loading"`: render a minimal centered spinner/blank
    state — **not** the page underneath (this is the actual fix for "page
    shell renders regardless of login state").
  - If `authState === "anonymous"` **and** `pathname !== "/login"`: redirect
    (`router.replace("/login")`) and render nothing while the redirect
    happens.
  - If `authState === "authenticated"` **and** `pathname === "/login"`:
    redirect to `/board` (a logged-in user visiting `/login` shouldn't see
    the login form again — small UX nicety, not strictly required but cheap
    and expected).
  - Otherwise: render `{children}` normally.
  - Must special-case `pathname === "/login"` explicitly (skip the "must be
    authenticated" branch) to avoid a redirect loop, since `/login` is the
    one route that must render for anonymous visitors.

- Wiring: `frontend/src/app/layout.tsx` stays a server component (keeps
  `metadata` export working, per Next.js App Router constraints — client
  components can't export `metadata`), but wraps its children:
  ```tsx
  <body className="font-sans antialiased">
    <AuthGate>
      <NavBar />
      {children}
    </AuthGate>
  </body>
  ```
  Wrapping `NavBar` too so it can read `useAuth()` for a real "logged in as
  X — Log out" state instead of the current static "Log in" link.

### 8.3 What this does *not* need to change

- No server-side session/cookie mechanism — the app is a token-in-
  `localStorage` SPA today (`frontend/src/lib/api.ts`'s `authHeaders()`) and
  nothing here proposes changing that transport; `AuthGate` is purely a
  client-side redirect guard layered on top of the existing token flow.
- No changes to individual pages' own data-fetching code — once `AuthGate`
  guarantees a page only ever renders when `authState === "authenticated"`,
  the existing `useEffect(() => api.listProjects()...)`-style fetches in
  `page.tsx`/`reports/page.tsx`/etc. are safe as-is (a valid token is
  guaranteed to exist by the time they run). The inline `{error && ...}`
  banners can stay as a fallback for *other* failure modes (network errors,
  403s from bad manager scoping, etc.), they just stop being the
  *only* signal for "you're not logged in."
- `admin/page.tsx`'s own currentUser/role check can be simplified once it
  reads `role` from the shared `AuthContext` instead of its own `api.me()`
  call, but its "not an admin → show a message" behavior (as opposed to a
  hard redirect) is reasonable to keep — a logged-in non-admin hitting
  `/admin` isn't the same "you're not authenticated" case `AuthGate` handles,
  it's "you're authenticated but not authorized," which is fine to render
  inline rather than redirect away from.

### 8.4 Data shape the designer needs

```ts
interface AuthContextValue {
  user: User | null;           // existing User type, + is_active (§5.7)
  authState: "loading" | "anonymous" | "authenticated";
  logout: () => void;          // clears localStorage token, sets state to "anonymous"
}
```
No new API endpoint needed for this — it's built entirely on the existing
`GET /users/me` and the existing token in `localStorage`.

---

## 9. Timer endpoint changes for admin override + correct attribution

### 9.1 `POST /time-entries/start` — tighten to assignee-only (**PROPOSED CHANGE**)

**GAP found during this audit**: `start_timer` currently calls
`assert_can_edit_task`, which — per `services/authz.py::can_edit_task` —
allows the task's **assignee, creator, or any admin**. But the resulting
`TimeEntry.user_id` is always `current_user.id` (whoever called the
endpoint), not the task's assignee. So today, a task's *creator* (if
different from its assignee) or an *admin* can start a timer on someone
else's task, and the logged time gets attributed to the creator/admin, not
the person actually doing the work — silently wrong data for every
time-based report.

Fix: for `start` specifically (not `pause`/`resume`/`stop`, see §9.2),
require `current_user.id == task.assignee_id`, dropping the
creator/admin bypass for this one action only.

| Caller | Before (today) | After (this change) |
|---|---|---|
| Task's assignee | Allowed | Allowed (unchanged) |
| Task's creator (not the assignee) | Allowed — **misattributes time to the creator** | `403` |
| Admin | Allowed — **misattributes time to the admin** | `403` |
| Anyone else | `403` (unchanged) | `403` |

### 9.2 `pause` / `resume` / `stop` — add an admin override (**PROPOSED CHANGE, new capability**)

Today `_get_owned_entry` in `routers/time_entries.py` hard-filters to
`entry.user_id == current_user.id` before `assert_can_edit_task` is even
reached — so **even an admin gets a 404** trying to touch another user's
time entry (confirmed by the existing test
`test_manager_cannot_start_pause_or_stop_reports_timer`, which asserts `404`
for a manager, but the same code path applies uniformly to admins too — no
admin-specific carve-out exists anywhere in `time_entries.py` today).

This is a real operational gap for item 4's "Admins: full access": there is
currently no way for an admin to pause or stop a timer someone left running
(e.g., over a weekend), and it directly blocks the deactivation flow in
§6.4 — if a deactivated user's timer needs to be resumed or force-stopped
later (e.g., their task is reassigned), nobody can ever do it, since the
original owner can no longer log in and no one else has any path to that
`TimeEntry` row.

Fix: change `_get_owned_entry` to allow an admin to fetch *any* entry by id
(bypassing the ownership filter), while non-admins keep the existing
ownership-or-404 behavior. `assert_can_edit_task` already passes
unconditionally for admins, so no change needed there.

| Action | Employee (non-owner) | Manager (non-owner, incl. own report's entry) | Admin |
|---|---|---|---|
| `start` | `403` (unchanged) | `403` (unchanged) | `403` — **new restriction**, §9.1 |
| `pause` | `404` (unchanged — ownership check first) | `404` (unchanged) | **Allowed — new** |
| `resume` | `404` (unchanged) | `404` (unchanged) | **Allowed — new** |
| `stop` | `404` (unchanged) | `404` (unchanged) | **Allowed — new** |

Note the asymmetry is intentional: `start` gets *stricter* (even admin loses
it) because starting always attributes new time to `current_user`, which
must stay tied to whoever is actually about to do the work; `pause`/
`resume`/`stop` act on time already attributed to the original owner and
don't change that attribution, so an admin override there is safe and
purely operational (banking/closing out someone else's already-logged
segment, not creating a new one under the wrong identity).

Managers are **deliberately excluded** from this override, consistent with
the PRD's "review only" — this override is an admin operational tool, not a
manager capability.

---

## 10. Reports scoping (**PROPOSED CHANGE**)

### 10.1 Current state (gap)

`routers/reports.py`'s `_completed_tasks()` helper — used by `cycle-time`,
`control-chart`, `lead-time`, `throughput`, and (via a separate query)
`cumulative-flow` — filters only by `status == COMPLETED` and optionally
`project_id`. **It applies no role/ownership scoping at all.** Every
authenticated user, regardless of role, currently sees cycle-time/lead-time/
throughput/CFD data for every task in the system, including tasks they have
no relationship to. This directly conflicts with the assignment's "Employees:
only their own tasks/timers."

Contrast with `routers/notifications.py::reminder_candidates`, which
**already does exactly the right thing** (admin: everyone; manager: direct
reports via `manager_id`; employee: self) — **CONFIRMED as the existing
precedent** this design copies rather than invents fresh.

### 10.2 Fix

Apply the same visibility rule `GET /tasks` already uses (`routers/tasks.py`,
lines building the `or_(...)` filter) to the task set every reports endpoint
starts from:

| Role | Task set reports are computed over |
|---|---|
| Employee | Tasks they're the assignee or creator of |
| Manager | The above, **plus** tasks assigned to their direct reports (`Task.assignee.has(User.manager_id == current_user.id)`) |
| Admin | All tasks (unchanged) |

No new query params — this is derived from `current_user`, exactly like
`notifications.py` already does it and exactly like `GET /tasks` already
does it for the board. `project_id` stays as an additional filter on top,
unchanged. Response shapes (`CycleTimePoint`, `LeadTimePoint`,
`ThroughputBucket`, `CumulativeFlowPoint`) are unchanged — this only narrows
which tasks feed them.

**Scope confirmation** (per the brief's explicit request to re-check this):
PRD §"Primary Users" says "Line Managers: review team time spent on tasks
(review only)" and gives no indication of multi-level ("reports of
reports") hierarchies — and no code anywhere in this app (task visibility,
notifications, or this new reports scoping) does recursive manager-chain
traversal. **Direct reports only**, consistently, everywhere `manager_id`
scoping appears in this app. If skip-level visibility is wanted later, it
needs a recursive CTE or a materialized closure table — out of scope now,
flagged the same way `docs/design/kanban-timer-design.md` §1.4 flags its own
deferred literal-interpretation option.

---

## 11. `time-entries` list scoping for manager review (**PROPOSED CHANGE, closes a real functional gap**)

### 11.1 The gap

`GET /time-entries` (`routers/time_entries.py::list_time_entries`) is
hardcoded to `filter(TimeEntry.user_id == current_user.id)` — a manager has
**no way at all**, today, to fetch their direct reports' time entries. This
is a direct contradiction of the PRD's core manager use case ("Line
Managers: review team time spent on tasks"): the manager-scoped task filter
exists (`GET /tasks?manager_id=`), but the time-entry data itself — the
actual thing being reviewed — is unreachable for anyone but the entry's
owner or by inference through `TaskDetailPanel`'s existing
`useCompletedEntry` gap (already flagged in `frontend/src/board/session.ts`'s
own comment: *"GET /time-entries only ever returns the caller's own
entries... for anyone else... it stays null"*).

### 11.2 Fix

Extend `GET /time-entries` with two new optional query params, additive and
backward compatible (no params → current behavior, caller's own entries,
unchanged):

```
GET /time-entries?task_id=&user_id=&manager_id=
```

| Param | Who can use it | Behavior | Error |
|---|---|---|---|
| (none) | anyone | Caller's own entries (existing, unchanged) | — |
| `user_id={id}` | Caller themself, that user's direct manager, or admin | Entries for that one user | `403` if caller is neither the target, their manager, nor admin |
| `manager_id={id}` | That manager themself, or admin | Entries for every user whose `manager_id == manager_id` | `403` if caller is neither that manager nor admin |
| `task_id` | anyone (existing) | Combines with the above as an additional filter, unchanged | — |

`manager_id` and `user_id` are mutually exclusive in a single request
(`400` if both given) to keep the semantics unambiguous. Response shape
(`TimeEntryRead[]`) is unchanged.

This is read-only, matches "review only" — none of `pause`/`resume`/`stop`
gain any manager-facing capability (§9.2's admin override stays admin-only).

---

## 12. `projects.py` — tighten to admin-gated mutations (**PROPOSED CHANGE**)

Found during the "audit every route" pass (item 4): `routers/projects.py`
has **zero role/ownership checks** on any endpoint — any authenticated user
can create or delete *any* project, and `delete_project` has no guard
against deleting a project that still has tasks linked to it (`Task.project_id`
has no `ondelete` behavior specified, so this has the same silent-orphan /
FK-violation risk described in §6.1, just at the project→task level instead
of user→task).

This wasn't explicitly named in the request, but falls squarely under item
4's "first-time full audit of every route for auth coverage." Proposed,
consistent with treating projects as part of the admin-configurable surface
(alongside board config and custom fields, which are already admin-gated):

| Endpoint | Before | After |
|---|---|---|
| `GET /projects`, `GET /projects/{id}` | Any authenticated user | Unchanged — needed for the project picker/filter available to everyone |
| `POST /projects` | Any authenticated user | Admin only (`assert_admin`) |
| `DELETE /projects/{id}` | Any authenticated user, no guard | Admin only, **plus** `409` if any `Task.project_id == id` exists (mirrors the existing task-delete-with-time-entries guard pattern in `routers/tasks.py::delete_task`) |

Flagged explicitly as new scope beyond the five numbered asks, since it's
adjacent but real — happy to defer this specific item if the PM wants to
keep this change strictly to what was asked; noting it here so it isn't
silently missed in the "audit every route" pass either way.

---

## 13. Full permission matrix

`E` = employee, `M` = manager, `A` = admin. "Own" = assignee, creator, or
(for time entries) the entry's owner. Unless noted, unauthenticated callers
get `401` everywhere except `POST /auth/login`.

| Endpoint | E (own) | E (other's) | M (own) | M (direct report's) | M (other's, not a report) | A |
|---|---|---|---|---|---|---|
| `POST /auth/login` | — public — | | | | | |
| ~~`POST /auth/register`~~ | **removed — 404 for everyone** | | | | | |
| `GET /users/me` | ✅ (self) | n/a | ✅ | n/a | n/a | ✅ |
| `GET /users` | ✅ (active only) | | ✅ (active only) | | | ✅ (+ `include_inactive`) |
| `POST /users` | ❌ 403 | | ❌ 403 | | | ✅ |
| `PATCH /users/{id}` | ❌ 403 (except own via `/me/password`, not this route) | | ❌ 403 | | | ✅ |
| `PATCH /users/me/password` | ✅ (self only) | n/a | ✅ | n/a | n/a | ✅ |
| `POST /users/{id}/reset-password` | ❌ 403 | | ❌ 403 | | | ✅ |
| `DELETE /users/{id}` | ❌ 403 | | ❌ 403 | | | ✅ (409 if last active admin) |
| `GET /projects`, `GET /projects/{id}` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `POST /projects` | ❌ 403 (new) | | ❌ 403 (new) | | | ✅ |
| `DELETE /projects/{id}` | ❌ 403 (new) | | ❌ 403 (new) | | | ✅ (409 if has tasks) |
| `GET /tasks` (list) | ✅ (filtered to own) | — (excluded from results) | ✅ | ✅ (via `manager_id=` or default scoping) | — (excluded) | ✅ (all) |
| `POST /tasks` | ✅ | n/a | ✅ | n/a | n/a | ✅ |
| `GET /tasks/{id}` | ✅ | ❌ 403 | ✅ | ✅ | ❌ 403 | ✅ |
| `PATCH /tasks/{id}` | ✅ | ❌ 403 | ✅ | ❌ 403 (review only) | ❌ 403 | ✅ |
| `DELETE /tasks/{id}` | ✅ (409 if has time entries) | ❌ 403 | ✅ | ❌ 403 | ❌ 403 | ✅ |
| `GET/POST /tasks/{id}/comments` | ✅ | ❌ 403 | ✅ | ✅ (view+post — comments aren't gated by edit rights, existing behavior, unchanged) | ❌ 403 | ✅ |
| `GET /tasks/{id}/audit` | ✅ | ❌ 403 | ✅ | ✅ | ❌ 403 | ✅ |
| `GET /time-entries` (no params) | ✅ (own) | n/a | ✅ (own) | n/a | n/a | ✅ (own) |
| `GET /time-entries?user_id=` | ✅ (self only) | ❌ 403 | ✅ (self) | ✅ **(new, §11)** | ❌ 403 | ✅ (any) |
| `GET /time-entries?manager_id=` | ❌ 403 (not their own id as a manager scope) | | ✅ (their own id only) **(new, §11)** | n/a | ❌ 403 (someone else's team) | ✅ (any) |
| `GET /time-entries/open` | ✅ (own only, unchanged) | n/a | ✅ (own) | n/a | n/a | ✅ (own) |
| `POST /time-entries/start` | ✅ (must be assignee) | ❌ 403 | ✅ (must be assignee) | ❌ 403 | ❌ 403 | ❌ 403 **(tightened, §9.1)** |
| `POST /time-entries/{id}/pause` | ✅ (own) | ❌ 404 | ✅ (own) | ❌ 404 | ❌ 404 | ✅ (any) **(new, §9.2)** |
| `POST /time-entries/{id}/resume` | ✅ (own) | ❌ 404 | ✅ (own) | ❌ 404 | ❌ 404 | ✅ (any) **(new, §9.2)** |
| `POST /time-entries/{id}/stop` | ✅ (own) | ❌ 404 | ✅ (own) | ❌ 404 | ❌ 404 | ✅ (any) **(new, §9.2)** |
| `GET /admin/board-config` | ✅ (read, unchanged) | | ✅ | | | ✅ |
| `PATCH /admin/board-config` | ❌ 403 | | ❌ 403 | | | ✅ |
| `GET /admin/custom-fields` | ✅ (read, unchanged) | | ✅ | | | ✅ |
| `POST/DELETE /admin/custom-fields` | ❌ 403 | | ❌ 403 | | | ✅ |
| `GET /reports/*` (all 5) | ✅ (own tasks only) **(new scoping, §10)** | | ✅ (own + reports) **(new scoping)** | | | ✅ (all) |
| `GET /notifications/reminders` | ✅ (self only, unchanged) | | ✅ (direct reports, unchanged) | | | ✅ (all, unchanged) |

---

## 14. Summary for hand-off

**For backend-dev:**
1. `models.py`: add `User.is_active` (default `True`) and
   `User.deactivated_at` (§2.1); write/run the one-time Postgres `ALTER
   TABLE` if deploying against an existing database (§2.2).
2. `core/config.py`: add `bootstrap_admin_email`, `bootstrap_admin_password`,
   `bootstrap_admin_name` settings; new `services/bootstrap.py::ensure_bootstrap_admin`;
   wire into `main.py`'s `lifespan` (§3.4); update `render.yaml` (§3.4);
   optional `scripts/seed_admin.py` (§3.5).
3. `routers/auth.py`: delete the `register` endpoint; add the `is_active`
   check to `login` (§4.1).
4. `deps.py::get_current_user`: add the `is_active` check (§4.1).
5. `schemas.py`/`routers/users.py`: new `POST /users`, `POST
   /users/{id}/reset-password`, `PATCH /users/me/password`, `DELETE
   /users/{id}`; extend `UserUpdate`/`UserRead` (§5, §6.4, §6.6); add
   `manager_id`/`assignee_id` active-user validation (§6.5, §7.2).
6. `routers/time_entries.py`: restrict `start` to the task's assignee only
   (§9.1); add admin bypass to `_get_owned_entry` for
   `pause`/`resume`/`stop` (§9.2); extend `GET /time-entries` with
   `user_id`/`manager_id` params (§11).
7. `routers/reports.py`: apply role-based task-set scoping to
   `_completed_tasks()` and the `cumulative-flow` query (§10).
8. `routers/projects.py`: admin-gate `POST`/`DELETE`, add the has-tasks
   delete guard (§12).
9. **Test/fixture migration** (not optional — this is a breaking change to
   how every existing test bootstraps a user): `backend/tests/conftest.py`'s
   `auth_headers` fixture and every helper in
   `test_authorization_and_guards.py` that calls `client.post("/auth/register",
   ...)` will break the moment that route is deleted. These need to move to
   seeding a bootstrap admin (e.g., a test-only `Settings` override or a
   direct DB insert via the test session) and then using `POST /users` (as
   that admin) to create the employee/manager accounts the tests currently
   create via self-registration.

**For designer:**
1. Login page (`app/login/page.tsx`): remove the register/login mode toggle
   entirely — login-only form, no "Create your account" copy (§4.1).
2. New `AuthProvider`/`AuthGate` (§8.2) wrapping the root layout; redirect
   anonymous visitors to `/login` from every route; redirect authenticated
   visitors away from `/login`. `NavBar` should reflect real session state
   (logged-in user + logout) instead of a static "Log in" link.
3. New admin screens/sections (extending `app/admin/page.tsx`): create-user
   form (email, full name, role, manager picker restricted to
   manager/admin-role users per §7.3, initial password field), edit-user
   fields (name/email/role/manager), reset-password action, and a
   deactivate/reactivate toggle that greys out (not removes) inactive rows
   and shows the `reports_affected` count from §6.5's open question if that
   gets built.
4. "Add Task" button + right-side slide-over panel replacing the inline
   `NewTaskForm` at the top of the board (item 5) — same fields, same
   `board.createTask(...)` call, purely a layout change; confirmed no API
   contract change needed.

**Confirmed as already correct, no rework needed:** every non-auth backend
endpoint already requires a bearer token (§4.2); task read/edit ownership
checks (§13's task rows); comments/audit visibility; board-config/
custom-fields admin gating; the existing `notifications.py` manager-scoping
pattern (§10.1), which this design explicitly extends rather than
reinvents; `POST /tasks`'s contract for the slide-over UI change (item 5).
