# Custom Fields, Admin CRUD & Board Cleanup — Design Document

Status: draft for backend-dev + designer hand-off (design only, nothing here
is implemented)
Owner: solution architect
Source of truth: `docs/PRD.md`
Reviewed against: `backend/app/models.py`, `backend/app/schemas.py`,
`backend/app/routers/admin.py`, `backend/app/routers/projects.py`,
`backend/app/routers/tasks.py`, `backend/app/routers/users.py`,
`backend/app/services/tasks.py`, `backend/app/services/users.py`,
`backend/app/services/authz.py`, `frontend/src/app/admin/page.tsx`,
`frontend/src/app/admin/UserManagement.tsx`, `frontend/src/app/page.tsx`,
`frontend/src/app/board/AddTaskPanel.tsx`, `frontend/src/app/board/TaskCard.tsx`,
`frontend/src/app/board/TaskDetailPanel.tsx`, `frontend/src/app/board/TimerControls.tsx`,
`frontend/src/board/session.ts`, `frontend/src/components/NavBar.tsx`,
`frontend/src/lib/types.ts`.

Same conventions as `docs/design/kanban-timer-design.md` and
`docs/design/auth-rbac-design.md`: **CONFIRMED** means current behavior
already matches the target and needs no rework; **GAP** flags a real problem
in the current code; **PROPOSED CHANGE** is a new rule/endpoint/column being
introduced by this design.

**Scope check against the timer/status state machine** (per this role's
standing responsibility to review it for every feature): none of the seven
items below add a new `TaskStatus` value, a new `TimerStatus` value, or a new
transition. Item 5's task archiving is deliberately orthogonal to `status`
(an archived task keeps whatever status it had — see §5). No change to
`docs/design/kanban-timer-design.md` §3's transition table is needed or
proposed here.

---

## 0. Cross-cutting finding: there is no task-edit UI at all today

Before designing items 1 and 3 (which both assume an "Add/Edit Task panel"),
it's important to state precisely what exists, because it's less than the
prompt implies:

- **CONFIRMED**: `AddTaskPanel.tsx` is create-only (title says "New task"; on
  submit it calls `board.createTask(...)` and closes). There is no
  corresponding "Edit Task" panel or edit mode anywhere.
- **CONFIRMED**: `TaskDetailPanel.tsx` — the only other task-facing panel —
  renders the task's fields **read-only** (title, badges, assignee/creator
  line, description) plus the timer, comments, and audit trail. It has no
  input for title/description/category/priority/assignee/project and no
  delete/archive button. The only way a task's fields change today is (a)
  drag-and-drop status changes on the board, (b) the timer endpoints, or (c)
  a raw API call.
- **GAP**: items 1 ("real inputs on the Add/Edit Task panel") and 3 ("a
  simple optional Project dropdown on the Add/Edit Task panel") both need an
  *edit* surface that doesn't exist yet, not just new fields bolted onto the
  existing create-only panel.

**PROPOSED CHANGE**: give `TaskDetailPanel` an edit mode. Concretely: an
"Edit" affordance that turns the current read-only title/category/
priority/assignee/description block into the same input set `AddTaskPanel`
already uses (`Input`, `Select`, category-other-text conditional, etc.), plus
the new project dropdown (§3) and custom-field inputs (§1), submitting via
`PATCH /tasks/{id}`. This is the single piece of new frontend scaffolding
items 1 and 3 both build on — called out once here rather than duplicated in
each section below. Visible only when `board.canEditTask(task)` is true
(same gate `TimerControls` already uses), matching `assert_can_edit_task`
(assignee, creator, or admin — not a viewing manager).

---

## 1. Custom fields: text/dropdown/date inputs on Add/Edit Task

### 1.1 Current state

**CONFIRMED — storage and type support already correct, no schema change
needed for types themselves:**
- `CustomFieldType` (`models.py`) already has five members:
  `text | number | select | date | boolean`. Text, dropdown (`select`), and
  date are all already there — no new enum value needed.
- `TaskCustomValue` (`models.py`) already stores one row per
  `(task_id, field_id)` with a single string `value` column — already the
  right shape for "per-task value keyed by field," for any field type
  (numbers/dates/booleans are stored as their string representation, same
  pattern the rest of this app uses for typed-but-string-stored data, e.g.
  `TaskCategory`/`TaskPriority` today).
- `TaskUpdate.custom_values: dict[str, str] | None` (`schemas.py`) already
  exists and is already wired in `PATCH /tasks/{id}` (`routers/tasks.py`,
  `update_task`) — it upserts one `TaskCustomValue` row per key, 400s on an
  unknown `field_id`, and records an `UPDATED` audit entry. This part needs
  no rework.
- `TaskRead.custom_values: dict[str, str] = {}` is already populated on
  every read (`_custom_values_map` in `routers/tasks.py`) — the read side is
  already correct too.

**GAP — creation has no path to set custom values in one call:**
- `TaskCreate` = `TaskBase`, and `TaskBase` has no `custom_values` field at
  all. Today the only way to set a custom value on a brand-new task is
  `POST /tasks` then immediately `PATCH /tasks/{id}` with `custom_values` —
  two round-trips, and a task briefly exists with none of its custom fields
  set. Minor, but real, and easy to close (§1.3).

**GAP — no value-shape validation per field type, on either create or
update:**
- `update_task`'s custom-values loop only checks that `field_id` refers to
  an existing `CustomFieldDefinition` — it accepts any string as the
  `value` regardless of `field_type`. A `date` field can be set to `"banana"`
  and a `select` field can be set to a value that isn't one of its
  configured options. Not called out in the original ask, but directly
  relevant to "real inputs" actually meaning something server-side (§1.3).

**GAP (the one explicitly named in the ask) — no rendering anywhere in the
frontend:**
- `AddTaskPanel.tsx`: never fetches `GET /admin/custom-fields`, never
  renders any custom-field input, never includes `custom_values` in its
  `board.createTask(...)` call. Confirmed by reading the full file — the
  form only has title/category/type/priority/assignee/description.
- `TaskCard.tsx`: never reads `task.custom_values` at all — no compact
  display of any kind.
- `TaskDetailPanel.tsx`: never reads `task.custom_values` either — no full
  display, and (per §0) no edit surface to begin with.

### 1.2 Data model changes

No new tables for this item alone (the dropdown-options table in §2 is
shared infrastructure, introduced there). One additive schema field:

```python
# schemas.py
class TaskCreate(TaskBase):
    custom_values: dict[str, str] | None = None   # NEW
```

`TaskBase` itself is left untouched (adding it there would leak into
`TaskRead`, which already declares its own read-populated `custom_values`
with a different default/semantic — write-optional vs. read-always-present).

### 1.3 API contract changes

**`POST /tasks`** (extended, additive/non-breaking — new optional field)
- Body gains `custom_values: dict[field_id, value] | null`.
- Behavior: after the task row is created and flushed (so `task.id` exists),
  apply the same per-entry validation and upsert `update_task` already does,
  via a new shared helper:
  ```python
  # services/tasks.py (PROPOSED)
  def apply_custom_values(db: Session, task: Task, values: dict[str, str]) -> None:
      for field_id, value in values.items():
          field_def = db.get(CustomFieldDefinition, field_id)
          if not field_def:
              raise HTTPException(400, f"Unknown custom field '{field_id}'")
          validate_custom_value(field_def, value)   # NEW, see below
          ...upsert TaskCustomValue...
  ```
  `create_task` and `update_task` both call this instead of duplicating the
  loop (refactor, not a behavior change for the update path).
- 201 → `TaskRead` (now reflecting the submitted `custom_values` immediately,
  no second round-trip).
- 400 on an unknown `field_id` (unchanged behavior, now also reachable from
  create).
- 400 on a value that fails the new type-shape check (**PROPOSED, new**):

  | `field_type` | Validation | Example failure |
  |---|---|---|
  | `text` | any string, including empty | — |
  | `number` | must parse as `float` | `"abc"` → `400 "field 'Story Points' expects a number"` |
  | `date` | must parse as `YYYY-MM-DD` (`date.fromisoformat`) | `"next tuesday"` → `400` |
  | `boolean` | must be exactly `"true"` or `"false"` | `"yes"` → `400` |
  | `select` | must equal the `value` of one currently-**active** `DropdownOption` scoped to this field (see §2) | an option that was deactivated or never existed → `400 "'Legacy' is not a valid option for field 'Category tag'"` |

**`PATCH /tasks/{id}`** — same `validate_custom_value` check added to the
existing loop (tightening, not a new field). This is a **behavioral
tightening**: values that previously silently succeeded (e.g. an
out-of-range date string) now 400. Flagged as a breaking change for any
existing client/test relying on the previously-unchecked behavior — there
shouldn't be any real one yet since no UI writes custom values today.

### 1.4 Frontend rendering contract (data shape for the designer)

`CustomField` (extended — see §2 for the full shape change to `options`):

```ts
interface CustomFieldOption {
  id: string;
  value: string;   // what gets stored in TaskCustomValue.value / submitted
  label: string;   // what the <select> displays
  is_active: boolean;
  position: number;
}

interface CustomField {
  id: string;
  name: string;
  field_type: "text" | "number" | "select" | "date" | "boolean";
  options: CustomFieldOption[] | null;  // non-null only when field_type === "select"
  created_at: string;
}
```

Both `AddTaskPanel` (create) and the new `TaskDetailPanel` edit mode (§0)
fetch `GET /admin/custom-fields` once (already unauthenticated-read-friendly
— `list_custom_fields` has no `assert_admin` gate, confirmed) and render one
input per definition, keyed by `field.id`, collected into a
`Record<string, string>` submitted as `custom_values`:

| `field_type` | Input | Notes |
|---|---|---|
| `text` | `<Input type="text">` | — |
| `number` | `<Input type="number">` | Submit `String(value)`. |
| `date` | `<Input type="date">` | Native date input already produces/accepts `YYYY-MM-DD` — matches the server-side ISO check in §1.3 with no client-side reformatting needed. |
| `boolean` | `<Select>` with `Yes`/`No` (or a checkbox) | Submit `"true"`/`"false"` literal strings, not `true`/`false` JS booleans (the wire format is a string). |
| `select` | `<Select>` populated from `field.options.filter(o => o.is_active)`, `value={o.value}`, display `{o.label}` | If the task's *current* stored value doesn't match any active option (i.e., it was set before the option was deactivated), add it back into the rendered list as a disabled/greyed extra `<option>` so the field doesn't silently show blank — this is the "what happens to a task whose selected option gets deleted" question from §2, answered concretely here. |

**Task card (compact)** — `TaskCard.tsx`: render at most the first 2
custom fields that have a non-empty value for this task, as small `Badge`s
(`{field.name}: {displayValue}`), in the field-definition order returned by
`GET /admin/custom-fields`. For `select`, resolve `displayValue` via the
option's `label` (fall back to the raw stored `value` if the option was
deleted/deactivated, per the note above). Omitted entirely if the task has
no custom values set — no empty-state clutter on the card.

**Task detail (full)** — new "Custom fields" `Card` section in
`TaskDetailPanel`, listing *every* defined field (not just ones with a
value), each showing its current value or `"—"` when unset, editable inline
per the input table above, submitting a `PATCH /tasks/{id}` with
`custom_values: { [changedFieldId]: newValue }` (only the changed key, not
the whole map — smaller diffs, and avoids accidentally re-validating/
re-touching every other field's audit trail on every edit).

---

## 2. Admin-editable dropdown options: custom-field selects, category, priority

This is the harder problem named in the ask, so it gets the most detail.

### 2.1 Current state

**CONFIRMED:**
- `category` and `priority` are Python `enum.Enum` classes (`TaskCategory`,
  `TaskPriority` in `models.py`), each backing a SQLAlchemy `Enum(...)`
  column on `Task` — i.e., a **native DB enum / CHECK constraint**, not
  admin-editable data. `TaskBase.category: TaskCategory` /
  `priority: TaskPriority` in `schemas.py` enforce the exact same fixed set
  at the Pydantic layer.
- `CustomFieldDefinition.options` (`models.py`) is a single comma-separated
  `String` column, only ever written once, at field-creation time
  (`POST /admin/custom-fields` → `CustomFieldCreate.options: list[str] |
  None`, joined with `,`). There is no endpoint to add, rename, or remove a
  single option afterward — confirmed by reading the full `admin.py` router:
  only `GET/POST /admin/custom-fields` and `DELETE
  /admin/custom-fields/{id}` exist, nothing option-scoped.
- `TaskCategory.OTHER` has a real special case tied to it:
  `TaskBase._validate_other_text` (a Pydantic `model_validator`) requires
  `category_other_text` iff `category == TaskCategory.OTHER`. This must
  keep working under whatever replaces the enum.
- Grepped the rest of the backend (`routers/reports.py`,
  `routers/notifications.py`, `services/*`) — **no other code depends on
  `TaskCategory`/`TaskPriority` being Python enums** beyond `models.py` and
  `schemas.py`. `SwimlaneField`'s `category`/`priority` members just group by
  whatever string is currently stored in `Task.category`/`priority`, with no
  dependency on the enum's exact member set. This significantly de-risks
  the change proposed below — no reporting/swimlane logic needs to change.

### 2.2 Options considered

| Option | Effect | Verdict |
|---|---|---|
| A. Leave `category`/`priority` as native DB enums; admin can only reorder/relabel the fixed set in the UI, not add new values | Smallest change | **Rejected** — the ask is explicit: "add/edit/delete the option values," which includes adding genuinely new categories/priorities beyond the PRD's list (e.g. a new "Vendor Escalation" category an Operations lead wants later). A relabel-only UI doesn't satisfy that. |
| B. Generic reuse of `CustomFieldDefinition`: make `category`/`priority` two more rows in that table, dropping the dedicated `Task.category`/`priority` columns in favor of `TaskCustomValue` rows | Maximum reuse | **Rejected** — `category`/`priority` are PRD-mandated *core* task fields with their own validation (`category_other_text`), their own place in `TaskRead`'s top-level shape, and their own swim-lane grouping option; folding them into the generic (optional, admin-defined-from-scratch) custom-fields concept conflates "fields the PRD requires on every task" with "fields an admin bolted on," and would make `category`/`priority` optional/nullable the way custom fields are, which the PRD doesn't support (category is `nullable=False` and mandatory on every task). |
| **C. Keep `Task.category`/`Task.priority` as dedicated columns, but change their DB type from a native enum to a plain `String`, validated at the app layer against a new shared lookup table** | Moderate, surgical | **Chosen** |

### 2.3 Chosen design: one generic `DropdownOption` table, three scopes

Rather than three near-identical tables (`TaskCategoryOption`,
`TaskPriorityOption`, and a per-custom-field options table), one table
covers all three cases the ask lists — category, priority, and every
`select`-type custom field's options — via a `scope` discriminator. This is
the "reuse the `CustomFieldDefinition`/option concept generically" path the
brief floats, applied narrowly (one options table, not folding
category/priority into `CustomFieldDefinition` itself, per §2.2 option B's
rejection).

```python
# models.py (PROPOSED CHANGE — new table)
class DropdownOptionScope(str, enum.Enum):
    TASK_CATEGORY = "task_category"
    TASK_PRIORITY = "task_priority"
    CUSTOM_FIELD = "custom_field"

class DropdownOption(Base):
    __tablename__ = "dropdown_options"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    scope: Mapped[DropdownOptionScope] = mapped_column(Enum(DropdownOptionScope), nullable=False)
    custom_field_id: Mapped[str | None] = mapped_column(
        ForeignKey("custom_field_definitions.id"), nullable=True
    )  # set iff scope == CUSTOM_FIELD; null for task_category/task_priority
    value: Mapped[str] = mapped_column(String, nullable=False)   # stored on Task.category/priority or TaskCustomValue.value
    label: Mapped[str] = mapped_column(String, nullable=False)   # display text; defaults to value
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("uq_dropdown_option_scope_value", "scope", "custom_field_id", "value", unique=True),
    )
```

`Task.category`/`Task.priority` columns (**PROPOSED CHANGE, breaking at the
DB layer**):
```python
category: Mapped[str] = mapped_column(String, nullable=False)          # was Enum(TaskCategory)
priority: Mapped[str] = mapped_column(String, default="normal", nullable=False)  # was Enum(TaskPriority)
```
`TaskCategory`/`TaskPriority` Python enums are kept in `models.py`, but only
as the source list for seed data (§2.4) — no longer used as a SQLAlchemy
column type or a Pydantic field type.

`CustomFieldDefinition.options` (the old CSV column) is **dropped**;
`select`-type option storage moves entirely to `DropdownOption` rows with
`scope=custom_field`. Add the matching ORM relationships (mirroring the
cascade pattern `Task` already uses) so deleting a `CustomFieldDefinition`
cleans up after itself automatically (closes the minor GAP the kanban-timer
design doc flagged: *"does not cascade-clean `TaskCustomValue` rows... low
priority"* — resolved now, per this design's item 5 mandate to close
delete-related gaps rather than defer them):
```python
class CustomFieldDefinition(Base):
    ...
    values: Mapped[list["TaskCustomValue"]] = relationship(cascade="all, delete-orphan")       # NEW
    dropdown_options: Mapped[list["DropdownOption"]] = relationship(cascade="all, delete-orphan")  # NEW
```

### 2.4 Seed data — startup idempotent seed, same pattern as `ensure_bootstrap_admin`

New `services/bootstrap.py::ensure_default_dropdown_options(db)` (or added to
the existing bootstrap module if one already exists from the auth-rbac
design), called from `main.py`'s `lifespan` right after
`Base.metadata.create_all`:

- If `DropdownOption` already has any row with `scope == TASK_CATEGORY`:
  skip (never re-seeds a live table — same "only touches empty" idempotency
  as the admin-bootstrap seed).
- Else insert, `is_builtin=True`, one row per PRD category:
  `production_issue, urgent_request, meeting, support_ticket,
  cyber_security_request, platform_support, infrastructure, other` (label =
  the existing `TASK_CATEGORIES` display strings already in
  `frontend/src/lib/types.ts`, mirrored server-side).
- Same for `scope == TASK_PRIORITY` if empty: `normal`, `expedite`,
  `is_builtin=True`.

**Migration note** (same caveat the auth-rbac doc already raised for
`is_active`/`deactivated_at`, restated here since it applies again): this
project has no Alembic migrations; `create_all` only creates *new* tables
and does not `ALTER TABLE tasks ALTER COLUMN category TYPE VARCHAR`. On a
fresh dev DB this is a non-issue. **If this ships after real `Task` rows
exist in Postgres**, backend-dev needs an explicit one-time migration:
`ALTER TABLE tasks ALTER COLUMN category TYPE VARCHAR, ALTER COLUMN priority
TYPE VARCHAR` (safe — enum values and varchar are both text on the wire) run
before deploying the new backend code, plus a one-off script to copy
`CustomFieldDefinition.options` CSV values into `DropdownOption` rows before
the column is dropped. Given this app's current "no real data yet"
prototype status (confirmed by both prior design docs' identical caveat),
recommend doing this now while it's free, not after real data accumulates.

### 2.5 The `OTHER` special case, preserved

`TaskBase._validate_other_text` changes from comparing
`self.category == TaskCategory.OTHER` to `self.category == "other"` — a
literal string comparison, still a pure Pydantic-level check with no DB
access needed, so it stays a `model_validator` exactly as today. The
`DropdownOption` row with `scope=task_category, value="other"` is marked
`is_builtin=True` and additionally protected in the delete endpoint (§2.7):
attempting to deactivate `value == "other"` under `scope == task_category`
is rejected with a dedicated 409 message, distinct from the generic
`is_builtin` guard, so the error is legible ("Others is required by the
category_other_text mechanism and cannot be removed" vs. the generic
"cannot remove a built-in option").

### 2.6 Data-integrity question: what happens to a task whose option gets deleted?

Explicitly answered, matching the pattern the ask asked to flag:

- **"Delete" from the admin UI never removes historical data or the option
  row itself** — it sets `is_active = False` (same soft-delete precedent
  `docs/design/auth-rbac-design.md` §6 already established for `User`, cited
  here rather than inventing a new convention).
- Existing `Task.category`/`Task.priority`/`TaskCustomValue.value` rows
  already storing that option's `value` are **untouched** — they keep
  displaying with the option's (still-resolvable) `label`, they just
  disappear from the picker for **new** selections (§1.4's "add it back as a
  disabled extra option" rule covers the display side).
- Built-in options (`is_builtin=True`) — the 7 PRD categories + `other`, and
  `normal`/`expedite` — can never be deactivated or deleted at all (409),
  full stop, since the PRD names them explicitly as the required set.
  Admins may only add options *beyond* this floor, or deactivate options
  *they themselves added*.
- A hard `DELETE FROM dropdown_options` row-removal path is deliberately
  **not** offered anywhere — there is no user-facing action that produces
  it. This avoids ever producing a `Task.category` value with no
  `DropdownOption` row at all to resolve a label from (the fallback in
  §1.4/§2.7 — "show the raw stored value if no matching option exists" —
  exists as a defensive measure for pre-existing data during the migration
  in §2.4, not as a normal operational path).

### 2.7 API contract

**`GET /admin/dropdown-options`** — list options. No admin gate (read-open,
matching `GET /admin/custom-fields`/`GET /admin/board-config` today — the
board/Add-Task panel need this for everyone, not just admins).
- Query params: `scope` (required, one of `task_category|task_priority|
  custom_field`), `custom_field_id` (required iff `scope=custom_field`,
  400 otherwise), `include_inactive` (bool, default `false` — non-admins
  get `false` forced regardless of what they pass, mirroring
  `GET /users?include_inactive` from the auth-rbac design; admins may pass
  `true` to see deactivated options in the admin editor).
- 200 → `DropdownOptionRead[]`:
  ```json
  {
    "id": "uuid", "scope": "task_category|task_priority|custom_field",
    "custom_field_id": "uuid|null",
    "value": "str", "label": "str",
    "is_builtin": false, "is_active": true, "position": 0,
    "created_at": "iso8601"
  }
  ```
- 400 if `scope` missing/invalid, or `custom_field_id` missing for
  `scope=custom_field`, or `custom_field_id` references a field whose
  `field_type != select`.

**`POST /admin/dropdown-options`** — admin only.
- Body: `{ "scope": "...", "custom_field_id": "uuid|null", "value": "str", "label": "str|null" }`
  (`label` defaults to `value` if omitted).
- 201 → `DropdownOptionRead` (`is_builtin: false`, `is_active: true`,
  `position` = current max + 1 within that scope/field).
- 400: `scope` invalid; `custom_field_id` required/invalid for the given
  scope; `custom_field_id` field isn't `select`-typed; `(scope,
  custom_field_id, value)` already exists (unique constraint, §2.3) — message
  distinguishes "already exists" from other 400s.
- 403 if not admin.

**`PATCH /admin/dropdown-options/{id}`** — admin only.
- Body: `{ "label": "str|null", "is_active": "bool|null", "position": "int|null" }`.
  **`value` and `scope`/`custom_field_id` are immutable after creation** —
  deliberately not editable here. Rationale: renaming the stored `value`
  (as opposed to its display `label`) would silently reinterpret every
  existing `Task`/`TaskCustomValue` row already holding the old value as an
  unrelated new one, with no audit trail of the reinterpretation. Renaming
  the *label* is safe and fully supported; changing what a value *means*
  is not offered — an admin who wants that should add a new option and
  deactivate the old one, which preserves history honestly.
- 200 → `DropdownOptionRead`.
- 404 not found. 403 not admin.
- 409 if `is_active: false` is requested on a row with `is_builtin: true`
  (§2.6), with the `other`-specific message from §2.5 when applicable.

**`DELETE /admin/dropdown-options/{id}`** — admin only. Despite the verb,
this **soft-deactivates** (sets `is_active = False`), same rationale as
`DELETE /users/{id}` in the auth-rbac design.
- 200 → `DropdownOptionRead` (`is_active: false`) — not 204, so the admin
  screen can grey the row in place rather than remove it (same reasoning as
  the user-deactivation response shape).
- 404 not found. 403 not admin. 409 if `is_builtin` (§2.6).

**`POST /admin/custom-fields`** (extended, behavior change not shape
change) — `CustomFieldCreate.options: list[str] | None` is kept as the
"create a field and seed its initial options in one call" convenience
shape; internally it now inserts one `DropdownOption(scope=custom_field,
custom_field_id=<new field>, value=opt, label=opt, is_builtin=False)` per
entry instead of writing a CSV string. No request-shape change; response
shape changes (below).

**`CustomFieldRead.options`** (**PROPOSED CHANGE, breaking response
shape**): was `list[str] | None`, becomes `list[DropdownOptionRead] | null`
(non-null only when `field_type == "select"`). Any existing client reading
`options` as flat strings needs to switch to `.value`/`.label` — flagged
explicitly since this is a real wire-format break, mitigated by there being
no real UI consumer of this field yet (confirmed in §1.1).

**`DELETE /admin/custom-fields/{id}`** (**CONFIRMED already exists**, per
`routers/admin.py`; behavior tightened) — now cascades to both
`TaskCustomValue` and `DropdownOption` rows scoped to the deleted field
(via the new ORM relationships in §2.3), closing the kanban-timer design
doc's previously-deferred minor GAP. Response/status code unchanged (204).

### 2.8 Category/priority on the task endpoints

`TaskBase.category: TaskCategory` → `category: str = Field(min_length=1)`;
`priority: TaskPriority = TaskPriority.NORMAL` → `priority: str = "normal"`.

New service-layer check (DB access required, so it lives in
`services/tasks.py`, called from `create_task`/`update_task`, not in the
Pydantic model):
```python
def validate_dropdown_value(db: Session, scope: DropdownOptionScope, value: str, custom_field_id: str | None = None) -> None:
    exists = db.query(DropdownOption).filter(
        DropdownOption.scope == scope,
        DropdownOption.custom_field_id == custom_field_id,
        DropdownOption.value == value,
        DropdownOption.is_active.is_(True),
    ).first()
    if not exists:
        raise HTTPException(400, f"'{value}' is not a currently valid option")
```
- `POST /tasks` / `PATCH /tasks/{id}`: 400 if `category` or `priority` (when
  present in the payload) doesn't resolve to an active `DropdownOption` for
  that scope. This is a **new validation**, not present today (today any
  string outside the fixed Python enum was already rejected by Pydantic
  before it reached the handler — so behavior for *garbage* input is
  unchanged; what's new is that the valid set is now DB-driven instead of
  code-fixed, and admins can grow it).
- `TaskRead.category`/`priority`: `TaskCategory`/`TaskPriority` → `str`
  (**breaking response type**, same field names).

### 2.9 Before / after summary (category/priority representation)

| | Before | After |
|---|---|---|
| DB column type | Native `Enum(TaskCategory)` / `Enum(TaskPriority)` | Plain `String`, app-validated |
| Adding a new category/priority | Requires a code change + redeploy (edit the Python enum) | `POST /admin/dropdown-options` at runtime, admin-only |
| Removing/hiding one | Not possible at all | `DELETE /admin/dropdown-options/{id}` (soft, blocked for built-ins) |
| `category_other_text` requirement | Pydantic check vs. `TaskCategory.OTHER` | Pydantic check vs. literal `"other"` (same mechanism, string instead of enum member) |
| `TaskRead.category`/`priority` wire type | Fixed enum string | Free string (validated against live DB state, not the OpenAPI schema) |
| Swim-lane grouping by category/priority | Groups by enum value | Groups by string value — **no change**, confirmed no code depends on the enum's exact member set (§2.1) |

---

## 3. Remove the standalone Projects page

### 3.1 Current state

**CONFIRMED**: `POST /tasks` (via `TaskBase.project_id: str | None`) already
accepts `project_id` at creation. **GAP**: `PATCH /tasks/{id}`
(`TaskUpdate`) does **not** — `TaskUpdate` is a standalone `BaseModel` that
does not inherit `TaskBase` and does not declare `project_id` at all.
Confirmed by reading the full class in `schemas.py`. This means a task's
project link can be set at creation but never changed afterward through the
API today — a real gap for "Add/Edit Task panel" having a project dropdown
that works in edit mode (§0), not just create mode.

**PRD wording, checked exactly**: *"Project link: optional — tasks can be
standalone or linked to a project. Employees mostly create and start their
own tasks without needing a project."* Nothing in the PRD implies a
dedicated projects page/workflow — it's explicitly a lightweight, optional
attribute of a task.

**CONFIRMED**: `POST /projects` and `DELETE /projects/{id}` are *already*
admin-gated (`assert_admin`) with a 409-if-has-tasks delete guard, per
`routers/projects.py` as it exists today — this exactly matches what
`docs/design/auth-rbac-design.md` §12 proposed, so it's already shipped, not
something this design needs to add. `GET /projects`/`GET /projects/{id}`
remain open to any authenticated user (also already correct — needed for
the picker).

### 3.2 Should project creation stay reachable without a dedicated page?

Given `POST /projects` is **already admin-only**, an inline "+ New project"
option inside the Add/Edit Task panel's dropdown would 403 for every
non-admin user who tries it — the majority of users, per the PRD's own
framing that employees "mostly create tasks without needing a project."
Surfacing a control that fails for most users who'd click it is worse than
not having it there.

**PROPOSED CHANGE**: project creation moves to the admin page (a new small
"Projects" section, listing existing projects with name/description and a
create form + delete button, admin-only, using the already-existing
`POST`/`DELETE /projects` endpoints — no backend change needed here, purely
relocating the existing `page.tsx` project-creation form into `admin/
page.tsx`). The Add/Edit Task panel's project field is a **read-only
picker** populated from `GET /projects` (available to everyone), with a
"No project (standalone)" default/`null` option — no create affordance
inline.

### 3.3 Frontend changes (no other backend contract change needed beyond §3.1's `TaskUpdate.project_id` gap)

- Delete `frontend/src/app/page.tsx` entirely (or replace with a redirect to
  `/board` if Next.js's root route needs *something* to render — designer's
  call; functionally the page's content goes away).
- `NavBar.tsx`: remove the `{ href: "/", label: "Projects" }` entry from
  `LINKS`.
- `AddTaskPanel.tsx` **and** the new `TaskDetailPanel` edit mode (§0): add a
  `Project` `<Select>` (options from `GET /projects`, plus a "No project"
  entry mapping to `null`), wired into `board.createTask(...)`/the new
  `PATCH` call via `project_id`.
- `admin/page.tsx`: new "Projects" `Card` section (list + create form,
  moved from the deleted `page.tsx`; delete button per row, admin-only,
  already covered by existing 409-if-has-tasks backend behavior).

### 3.4 API contract change

```python
# schemas.py
class TaskUpdate(BaseModel):
    ...
    project_id: str | None = None   # NEW
```
`update_task` handler: no special validation needed beyond what
`assignee_id` already gets — actually, unlike `assignee_id`
(`validate_assignee_active`), there's currently **no existence check at all**
on `project_id` in `create_task` either (confirmed — `TaskBase.project_id`
has no validator, and `create_task` never calls `db.get(Project, ...)`).
**PROPOSED CHANGE**: add a `validate_project_exists(db, project_id)` check
(400 if a non-null `project_id` doesn't resolve to a real `Project` row),
applied in both `create_task` and the new `project_id` handling in
`update_task` — small, consistent with the assignee pattern, and prevents a
task silently pointing at a nonexistent project via a stale/mistyped id.

---

## 4. Kanban admin screen: relabel, don't restructure

### 4.1 Confirmed from the PRD and existing code

**CONFIRMED**: PRD's "Statuses" section: *"Statuses (fixed set of 5)...
Status modeling follows the same approach already used on the Product
Operation Reporting Next.js app."* `docs/design/kanban-timer-design.md`
§1.2 already resolved the PRD's internal tension (fixed statuses vs.
"admins can define a configurable Kanban workflow") in favor of: the
**5-status set is fixed and not admin-configurable**; only swim-lane
grouping and custom fields are admin-configurable. Re-confirmed here by
reading `models.py`'s `TaskStatus` enum (still exactly 5 fixed values, no
admin-editable status table exists) and `admin.py` (no status-related
endpoint exists at all — only `board-config` for swim lanes and
`custom-fields`). **Nothing in the current backend contract implies status
columns are configurable** — the user's complaint is about the *admin page's
labeling*, not an actual backend capability that needs removing.

### 4.2 The actual problem

`admin/page.tsx`'s only board-related section is a `Card` titled **"Kanban
board"**, containing a single control: "Swim lanes grouped by
[Team member/Task type/Category/Priority]." Nothing on the page mentions
columns or statuses, and the backend has no status-editing endpoint — but
the section's title ("Kanban board") reads as if it governs the board's
structure in general, which invites the misreading that the 5 status
columns themselves might be configurable there. This is a naming/IA
problem, not a functionality problem.

### 4.3 Proposed change — frontend only, no backend contract change

- Rename the `Card`'s title from **"Kanban board"** to **"Swim lanes"**.
- Update the label text from "Swim lanes grouped by" to something explicit
  about scope, e.g. *"Group board cards into swim lanes by:"* with a short
  caption underneath: *"The five status columns (Backlog → To Do → In
  Progress → On Hold → Completed) are fixed and not configurable here — this
  setting only controls the horizontal grouping within each column."*
- No change to `GET/PATCH /admin/board-config`, `BoardConfigRead`, or
  `SwimlaneField` — this section's backend contract is already correct
  (§4.1); only its title/copy in `admin/page.tsx` changes.

---

## 5. Admin delete/archive capability, expanded

### 5.1 Current state, precisely

**CONFIRMED — the exact current gate on `DELETE /tasks/{id}`**: it calls
`assert_can_edit_task(current_user, task)`
(`services/authz.py::can_edit_task`), which returns `True` for the task's
**assignee, creator, or any admin** — so an admin is *already* able to reach
this endpoint for any task (not gated to "own tasks only"). The 409 guard
("cannot delete a task with logged time") applies uniformly to whoever
calls it, admin included — there is currently no admin bypass of any kind.

**CONFIRMED — no delete/archive affordance exists in the frontend at all**:
neither `TaskCard.tsx` nor `TaskDetailPanel.tsx` renders any delete button
today, despite the backend endpoint existing. This is worth stating plainly
since it means "admin should be able to delete tasks" is currently blocked
by a missing UI control, not just a missing capability.

**CONFIRMED**: `DELETE /admin/custom-fields/{id}` already exists (per
`routers/admin.py`), admin-gated, 404 if not found — this part of item 5 is
already done; §2.7 only changes what it cascades to.

**NEW, per §2.7**: `DELETE /admin/dropdown-options/{id}` is the
option-level delete this item asks for — fully specified in §2.7, not
repeated here.

### 5.2 Should an admin be able to force-delete a task with logged time?

This is the tension `docs/design/kanban-timer-design.md` §1.2 explicitly
left open ("GAP — task deletion has no data-loss guard... Not a PRD
requirement explicitly, but a correctness risk worth flagging"). Resolving
it now, as instructed:

**No** — the 409 guard should apply identically to admins. Reasoning,
tied to the PRD: the PRD requires an audit trail ("required — visible to
the employee on their own entries") and five reporting views computed
entirely from `TaskStatusEvent`/`TimeEntry` history (cycle time, lead time,
throughput, CFD, control chart). A hard delete — admin or not — cascades
away every `TimeEntry`, `TaskComment`, `TaskAuditEntry`, and
`TaskStatusEvent` row for that task (`cascade="all, delete-orphan"` in
`models.py`, unchanged), which silently corrupts historical reporting
numbers and destroys the one thing the PRD says must be preserved. Giving
admins a "force" flag that bypasses this doesn't serve a real operational
need the PRD names (there's no PRD requirement that admins must be able to
permanently erase logged work) and directly conflicts with one it does name
(audit trail). **The guard is not weakened for admins.**

**What admins actually need instead — archiving (PROPOSED CHANGE, new
capability, new column):**

```python
# models.py
class Task(Base):
    ...
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # NEW
```

Archiving is **orthogonal to `status`** (an archived Backlog task is still
Backlog; an archived Completed task is still Completed) — it's a visibility
flag, not a workflow state, so it does not touch the timer/status state
machine in `docs/design/kanban-timer-design.md` §3 at all (per this
document's opening scope note).

- **`POST /tasks/{id}/archive`** (**NEW**, admin only)
  - 200 → `TaskRead` (`archived_at` now set). Idempotent — archiving an
    already-archived task just returns it unchanged (not an error).
  - 404 if task not found. 403 if not admin.
  - Records a `TaskAuditEntry` (`action=UPDATED`, detail
    `"Task archived by admin"`) — preserves the audit trail exactly, unlike
    a hard delete.
  - No status change, no cascade, no data loss of any kind.
- **`POST /tasks/{id}/unarchive`** (**NEW**, admin only) — symmetric,
  clears `archived_at`, 200 → `TaskRead`.
- **`GET /tasks`** gains `include_archived: bool = False` (**NEW** query
  param). Default excludes archived tasks from the board for everyone
  (matches "removed from view" intent). `include_archived=true` is
  admin-only (silently ignored for non-admins, same pattern as
  `include_inactive` on `GET /users`) — lets the admin screen show/manage
  archived tasks.
- **`GET /tasks/{id}`** — unaffected; an archived task is still directly
  fetchable by id (e.g. from a saved link or a report drill-down), it's
  only excluded from the default *list*.
- Reports (`routers/reports.py`) — **PROPOSED CHANGE**: exclude archived
  tasks from all five reporting endpoints by default, since "admin archived
  this, it's noise now" is the same intent as excluding it from the board.
  (Small, additive filter on the existing task-set queries — not detailed
  further here since it's a one-line `Task.archived_at.is_(None)` filter
  addition, not a new design question.)

**`DELETE /tasks/{id}`** itself is **unchanged**: still 409s (for anyone,
admin included) if the task has any `TimeEntry` row; still works (for
anyone with edit rights, admin included) for a genuinely time-free task —
e.g. a duplicate created by mistake and never started. This is the
"wherever it makes sense" the ask asks for: real deletion stays available
exactly where it's safe (no history to lose), and archiving is the answer
everywhere else.

### 5.3 Frontend: delete/archive affordance + confirmation

New capability in `TaskDetailPanel.tsx` (visible only when
`board.canEditTask(task)`, i.e. assignee/creator/admin):
- A "Delete task" button. On click: browser/`ConfirmDialog` confirmation
  ("Delete this task? This can't be undone.") → `DELETE /tasks/{id}`.
- If that call 409s (logged time exists) **and** the current user is an
  admin: replace the error toast with a follow-up prompt — "This task has
  logged time and can't be deleted. Archive it instead?" → confirms →
  `POST /tasks/{id}/archive`. Non-admin users just see the 409 message with
  no archive offer (they don't have that endpoint's permission anyway).
- `admin/page.tsx`: existing "Remove" button on each custom field
  (`handleDeleteField`) gains the same confirmation step (currently fires
  immediately with no confirmation at all — confirmed by reading
  `AdminPage`'s `handleDeleteField`, which calls `api.deleteCustomField`
  straight from the `onClick`). Same for the new per-option delete buttons
  in §2's option editor UI.

### 5.4 Permission matrix — new/changed delete-adjacent endpoints

`E` = employee, `M` = manager, `A` = admin. "Own" = assignee or creator.

| Endpoint | E (own) | E (other's) | M (any) | A |
|---|---|---|---|---|
| `DELETE /tasks/{id}` (no logged time) | ✅ | ❌ 403 | ❌ 403 | ✅ (any task) |
| `DELETE /tasks/{id}` (has logged time) | ❌ 409 | ❌ 403 | ❌ 403 | ❌ 409 (unchanged — no override, §5.2) |
| `POST /tasks/{id}/archive` | ❌ 403 | ❌ 403 | ❌ 403 | ✅ |
| `POST /tasks/{id}/unarchive` | ❌ 403 | ❌ 403 | ❌ 403 | ✅ |
| `DELETE /admin/custom-fields/{id}` | ❌ 403 | | ❌ 403 | ✅ (cascades per §2.3) |
| `DELETE /admin/dropdown-options/{id}` | ❌ 403 | | ❌ 403 | ✅ (soft; 409 if `is_builtin`) |
| `GET /tasks?include_archived=true` | n/a (ignored) | | n/a (ignored) | ✅ |

---

## 6. User profile view

### 6.1 What the PRD actually gives a basis for

Checked explicitly, per the ask: the PRD's "Primary Users" section names
only **Employees** and **Line Managers** as roles, with no mention of job
title, department, start date, or any other HR-style attribute anywhere in
the document. `User` (`models.py`) already carries exactly: `email,
full_name, role, manager_id, is_active, deactivated_at, created_at`.

**Conclusion: no new schema fields are justified.** Adding
title/department/start-date fields here would be scope creep with zero PRD
basis, on an internal tool the PRD explicitly scopes to task/time tracking,
not HR record-keeping. "Basic info" for this PRD's purposes **is** the
fields that already exist.

### 6.2 Design: a read view, not new schema

**PROPOSED CHANGE (frontend only)**: a `UserProfilePanel` (slide-over,
visually consistent with `TaskDetailPanel`'s pattern), opened by clicking a
user's name in `UserManagement.tsx`'s table (currently the name is plain
text, not a link/button — becomes clickable). Shows, read-only:

- Full name, email, role (`ROLE_LABEL`-formatted, as already done in the
  table).
- Manager: resolved name + email (looked up from the already-loaded
  `users` list client-side — no new fetch).
- Status: Active / Deactivated, and if deactivated, `deactivated_at`
  formatted via the existing `formatRelativeTime` helper (`board/format.ts`)
  — reuses existing formatting utilities rather than introducing new ones.
- Member since: `created_at`, same formatting.
- **Direct reports**: a derived list (`users.filter(u => u.manager_id ===
  this.id)`), purely computed client-side from data already fetched via
  `GET /users?include_inactive=true` — no new endpoint. This is the one
  piece of "more than name/email/role" the ask specifically calls out
  ("assigned manager... basic info") that has a real PRD-relevant basis
  (it's the same direct-report relationship `manager_id` already drives for
  task visibility and reporting scope), so it's included even though it's
  derived rather than a new field.

**No new backend endpoint is required** — `GET /users?include_inactive=true`
(admin) already returns every field this view needs for every user, and
the admin screen already loads that full list. A dedicated
`GET /users/{id}` is not proposed since nothing here needs single-record
fetching the list doesn't already provide.

### 6.3 Permission matrix

| Who can open the profile view | Behavior |
|---|---|
| Admin | Full read view for any user (via the admin page, where this lives) |
| Manager / Employee | Not exposed — this view lives inside `admin/page.tsx`, which is already gated to "admin role" at the page level (`AdminPage`'s existing `currentUser.role !== "admin"` check). Note: the *underlying data* (`GET /users`, no `include_inactive`) is already visible to every authenticated role today (§5.7 of the auth-rbac design, confirmed unchanged) — this section doesn't loosen or tighten that, it just doesn't build a *second* UI surface for non-admins to view it through. |

---

## 7. Task card timer display — total logged time for any viewer

### 7.1 Current state, precisely (the exact gap, confirmed by reading the code)

**CONFIRMED, and sharper than the prompt assumed**: `TaskCard.tsx`'s call to
`<TimerControls ... />` does **not** pass a `completedEntry` prop at all —
only `TaskDetailPanel.tsx` does (via `useCompletedEntry(task)`). Since
`TimerControls`'s `completedEntry` prop defaults to `null`
(`completedEntry = null` in its destructured props), **the board card shows
a bare "Completed" pill with no duration for every completed task, for
every viewer, including the task's own timer owner.** This is not "correct
for the owner, wrong for everyone else" — it's simply never wired on the
card at all. `TaskDetailPanel` is the one place duration shows today, and
only there, and only for the entry's owner (per `useCompletedEntry`'s own
comment in `board/session.ts`: *"GET /time-entries only ever returns the
caller's own entries... for anyone else... it stays null"*).

**CONFIRMED — why `useCompletedEntry` can't be fixed by widening
`GET /time-entries`'s params**: even after the auth-rbac design's proposed
`user_id`/`manager_id` params (§11 there), a task's **creator** (who can
view the task per `assert_can_view_task` but isn't the assignee, the
assignee's manager, or an admin) still has no legal way to fetch the
assignee's time entries — `GET /time-entries?user_id=` is scoped to "the
target themself, their manager, or admin" (auth-rbac §11.2), which doesn't
cover "task creator, different person from assignee." So even the widened
endpoint wouldn't close this gap for every viewer who's legitimately allowed
to *see* the task.

### 7.2 Fix: a server-computed total on `TaskRead` itself

Since `assert_can_view_task`/the `GET /tasks` list filter already correctly
gate *who can see a task at all*, the cleanest fix is to make total logged
time part of what "seeing the task" already includes — no separate
authorization surface to get right, no extra round-trip, works for every
viewer who can see the task, full stop.

```python
# schemas.py
class TaskRead(TaskBase, UTCModel):
    ...
    total_logged_seconds: float = 0.0   # NEW
```

```python
# routers/tasks.py — _serialize(), extended
def _total_logged_seconds(db: Session, task: Task) -> float:
    total = 0.0
    for entry in db.query(TimeEntry).filter(TimeEntry.task_id == task.id).all():
        total += entry.accumulated_seconds
        if entry.status == TimerStatus.RUNNING and entry.last_resumed_at:
            total += (datetime.utcnow() - entry.last_resumed_at).total_seconds()
    return total
```
Computed the same way `TimeEntryRead.elapsed_seconds` already is (banked
`accumulated_seconds` plus the live segment if currently running) — same
formula, just summed across every `TimeEntry` row the task has ever had
(normally one for a completed task, but this also correctly reports a
total for a task with an open paused/running entry, which is a bonus this
fix gives "for free" beyond just the completed-task case named in the ask).

**Performance note, stated rather than silently accepted**: this is one
extra query per task in `list_tasks`, i.e. N+1 for a board-sized list.
Acceptable at this app's current prototype scale (per both prior design
docs' identical framing of DB-level concerns as "low priority for the
prototype"); flagged as an easy follow-up optimization — replace the
per-task loop with a single aggregate query
(`SELECT task_id, SUM(accumulated_seconds) ... GROUP BY task_id`) joined
into `list_tasks` if/when board size makes N+1 queries a real latency
concern. Not blocking this design.

### 7.3 Frontend changes

- `TimerControls.tsx`: the `completedEntry?: TimeEntry | null` prop is
  **replaced** by reading `task.total_logged_seconds` directly (it's now on
  every `Task` the component already receives — no new prop needed at all).
  The `"Completed"` branch changes from
  `{completedEntry && <span>· {formatDuration(completedEntry.accumulated_seconds)}</span>}`
  to `{task.total_logged_seconds > 0 && <span>· {formatDuration(task.total_logged_seconds)}</span>}`.
- `TaskCard.tsx`: no change needed beyond the above — it already passes
  `task` into `TimerControls`, so it starts showing duration on completed
  cards for the first time, for every viewer.
- `TaskDetailPanel.tsx`: drop the `completedEntry={completedEntry}` prop
  and the `useCompletedEntry` hook call entirely — no longer needed.
- `board/session.ts`: `useCompletedEntry` can be **deleted** (its one
  caller goes away). Flagged explicitly since it's a real deletion, not
  just an unused-but-harmless leftover — leaving it in place would be a
  second, now-redundant/lower-fidelity code path computing the same thing
  `TaskRead.total_logged_seconds` now does correctly for everyone.

### 7.4 Permission matrix

| Viewer relationship to the task | Sees `total_logged_seconds` on the card? |
|---|---|
| Assignee (the entry's owner) | ✅ (unchanged experience, now via a cheaper path — no extra fetch) |
| Creator (not assignee) | ✅ (**fixed** — previously always blank) |
| Assignee's manager | ✅ (**fixed**) |
| Admin | ✅ (**fixed**) |
| Anyone who can't view the task at all | N/A — never receives the `TaskRead` in the first place (unchanged; existing `assert_can_view_task`/list-filter gating is untouched by this fix) |

---

## 8. Summary for hand-off

### For backend-dev

1. **`models.py`**: add `DropdownOption` + `DropdownOptionScope` (§2.3);
   change `Task.category`/`Task.priority` columns from `Enum(...)` to
   `String` (§2.3); drop `CustomFieldDefinition.options` CSV column, add
   `values`/`dropdown_options` cascade relationships (§2.3); add
   `Task.archived_at` (§5.2). Write the one-time Postgres migration if
   deploying against a non-empty DB (§2.4) — same caveat pattern as the
   auth-rbac design's `is_active` migration note.
2. **Seed data**: `ensure_default_dropdown_options()`, wired into
   `main.py`'s `lifespan` next to `ensure_bootstrap_admin` if that already
   exists (§2.4) — idempotent, only touches an empty scope.
3. **`schemas.py`**: `TaskCreate.custom_values` (§1.2); `TaskUpdate.
   project_id` (§3.4); `TaskBase.category`/`priority` → `str`, `_validate_
   other_text` compares to literal `"other"` (§2.5, §2.8); `TaskRead.
   total_logged_seconds` (§7.2); new `DropdownOptionRead`,
   `DropdownOptionCreate`, `DropdownOptionUpdate`; `CustomFieldOptionRead`
   and the `CustomFieldRead.options` shape change (§2.7, breaking).
4. **`services/tasks.py`**: `apply_custom_values` + `validate_custom_value`
   (§1.3); `validate_dropdown_value` (§2.8); `validate_project_exists`
   (§3.4); `_total_logged_seconds` helper (§7.2).
5. **`routers/tasks.py`**: wire `custom_values` into `create_task`; wire
   `project_id` into `update_task`; add `POST /tasks/{id}/archive` and
   `/unarchive`; add `include_archived` to `list_tasks`; compute and attach
   `total_logged_seconds` in `_serialize`.
6. **`routers/admin.py`**: new `GET/POST/PATCH/DELETE
   /admin/dropdown-options` endpoints (§2.7); update
   `create_custom_field`/`_serialize_field` for the new options shape;
   confirm `delete_custom_field`'s cascade now covers `DropdownOption` too.
7. **`routers/reports.py`**: add `Task.archived_at.is_(None)` to the
   existing task-set filters (§5.2) — small, additive.
8. **Tests**: every existing test that constructs a `Task` with
   `category=TaskCategory.X`/`priority=TaskPriority.Y` needs to switch to
   the plain string values (e.g. `"meeting"`, `"normal"`) — mechanical but
   not optional, since the enum types are gone from the schema layer.
   Fixtures will also need the default `DropdownOption` seed rows present
   (either via the startup seed running in the test DB too, or a
   test-fixture equivalent) before any task-creation test can pass
   `validate_dropdown_value`.

### For designer

1. **`AddTaskPanel.tsx`**: add custom-field inputs (§1.4, per-type table)
   and a Project `<Select>` (§3.3).
2. **`TaskDetailPanel.tsx`**: needs a genuinely new edit mode — today it has
   none at all (§0). Add editable title/description/category(+other text)/
   priority/assignee/project fields (reusing `AddTaskPanel`'s existing input
   patterns) plus the custom-fields section (§1.4) plus a delete/archive
   button with confirmation (§5.3). Drop the `completedEntry` prop/
   `useCompletedEntry` call (§7.3) — duration now comes from `task.
   total_logged_seconds` with zero extra plumbing.
3. **`TaskCard.tsx`**: add the compact custom-field badges (§1.4, max 2,
   populated-only) — no other change needed; total-logged-time display
   comes for free once `TimerControls` reads `task.total_logged_seconds`
   (§7.3).
4. **Remove** `frontend/src/app/page.tsx` and the "Projects" nav link in
   `NavBar.tsx` (§3.3).
5. **`admin/page.tsx`**: rename "Kanban board" → "Swim lanes" with the
   clarified copy (§4.3); add a "Projects" section (moved create/list UI,
   §3.2); add an options editor to each custom field row (add/edit
   label/deactivate an option, using `/admin/dropdown-options`, §2.7); add
   "Category options" and "Priority options" sections using the same
   options-editor component against `scope=task_category`/`task_priority`
   (§2.7); add confirmation dialogs to the existing custom-field "Remove"
   button and every new delete-ish action (§5.3); make user rows'
   names clickable to open the new read-only `UserProfilePanel` (§6.2).

**Confirmed as already correct, no rework needed:** `TaskCustomValue`
storage shape and all five `CustomFieldType` members (§1.1);
`TaskUpdate.custom_values` wiring on `PATCH /tasks/{id}` (§1.1);
`POST`/`DELETE /projects` admin-gating and the has-tasks delete guard
(§3.1); the fixed 5-status `TaskStatus` enum and the absence of any
status-editing backend surface (§4.1); `DELETE /admin/custom-fields/{id}`
existing and being admin-gated (§5.1); `assert_can_edit_task` already
allowing admin on `DELETE /tasks/{id}` (§5.1).
