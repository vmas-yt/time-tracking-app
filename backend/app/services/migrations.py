"""Minimal, dependency-free schema patcher.

This project has no Alembic migrations wired up — `Base.metadata.create_all`
(called in `app/main.py`'s `lifespan`) only creates *missing tables*; it never
`ALTER TABLE`s an existing one to add a newly-introduced column, nor changes
an existing column's type. That's fine for a brand-new database (the table is
created with every current column/type from a clean slate), but it silently
leaves an already-deployed database's schema behind whenever `models.py`
changes shape — every INSERT/SELECT referencing what's missing/mismatched
then fails (or, worse, silently misbehaves) at runtime.

`ensure_schema_migrations` closes that gap without requiring a manual
operator step or introducing a full migration framework: it inspects the
live schema and issues raw DDL/DML only for whatever is actually
missing/stale. Safe to call on every startup, and safe to call twice in a
row against the same engine — every check goes through `inspect(engine)`
(or a data-based `WHERE` condition) first rather than assuming a fresh
database, since SQLite's `ALTER TABLE ADD COLUMN` doesn't support
`IF NOT EXISTS` the way Postgres does, and Postgres won't let you `ALTER
COLUMN ... TYPE` twice from the same source type without erroring first
(the second run's column is already the target type, which is exactly the
no-op case each check below is against).

Covers, in order:
  1. `users.is_active` / `users.deactivated_at` (auth/RBAC overhaul).
  2. `tasks.archived_at` (docs/design/custom-fields-admin-design.md §5.2).
  3. `tasks.category` / `tasks.priority`: native Postgres `ENUM` -> `VARCHAR`,
     preserving data (§2.3/§2.4 there). SQLite never had a real native enum
     type at the DB level for these columns (SQLAlchemy's generic `Enum`
     type only adds a CHECK constraint on non-Postgres backends, and this
     project doesn't enable that), so there is nothing to convert there —
     this step is a Postgres-only concern, matching the design doc's own
     migration note, which only ever gives a Postgres `ALTER TABLE` command.
  4. `custom_field_definitions.options` (old CSV column) -> `dropdown_options`
     rows (`scope=custom_field`), then drop the column (§2.3/§2.4 there).
  5. Org structure Round A: bootstrap "General" Department/Team seed, plus
     `users.team_id` / `tasks.team_id` backfill onto it for pre-existing rows
     (see `_migrate_org_structure_backfill`'s own docstring for why this is
     *not* a `WHERE team_id IS NULL` style migration).
  6. RBAC Round B1 (additive schema only, zero behavior change): seed the 3
     builtin `roles` rows, add `users.role_id`, and backfill it from the
     legacy `users.role` enum column. Unlike step 5's `team_id`, this one
     *is* a `WHERE role_id IS NULL` style migration -- see
     `_migrate_rbac_schema_backfill`'s own docstring for why that's correct
     here despite the superficial similarity to step 5.
  7. RBAC Round B2 (schema half): relax `users.role` from `NOT NULL` to
     nullable, so a user holding a genuinely custom role (Round B3) has
     somewhere valid to leave the legacy column (NULL) once it no longer
     matches any of the 3 fixed `UserRole` members. No data is changed by
     this step -- every existing row's `role` value is left exactly as it
     is; only the column's nullability constraint moves. Postgres: a
     one-line `ALTER COLUMN ... DROP NOT NULL`. SQLite has no `ALTER
     COLUMN` at all, so `_migrate_users_role_nullable` does the
     create-copy-drop-rename table rebuild dance instead -- see that
     function's own docstring for the rollback-plan writeup and why the two
     backends are *not* symmetric on rollback.
  8. Manual/retroactive time-logging feature (schema only): three additive,
     nullable-or-defaulted columns on existing tables --
     `tasks.is_manual_entry` (bool, default False), `tasks.started_at`
     (nullable timestamp, deliberately a *new* column rather than reusing
     `tasks.first_in_progress_at` -- see that column's own docstring in
     `models.py`), `time_entries.is_manual` (bool, default False) -- plus
     one genuinely migration-relevant enum change:
     `task_audit_entries.action`'s underlying Postgres native `ENUM` type
     (`auditaction`) needs `MANUAL_TIME_LOGGED` added via `ALTER TYPE ...
     ADD VALUE`, verified empirically against real Postgres 16 (see
     `_migrate_audit_action_add_manual_time_logged`'s own docstring) rather
     than assumed safe. No backfill needed for any of the three columns --
     every pre-existing row's `False`/`False`/`NULL` defaults are exactly
     correct, since no historical task or time entry was ever manually
     logged. `manual_time_entry_settings` is a brand-new table, created
     entirely by `Base.metadata.create_all` -- no migration code needed for
     it at all.
  9. RBAC Round B3 (custom roles + granular permissions): `roles`/
     `role_permissions`/`users.role_id` already exist from Round B1/B2 (no
     further change to those); the only new schema surface is the brand-new
     `role_permission_audit_entries` table (see `RolePermissionAuditEntry` in
     models.py). Like `manual_time_entry_settings` above, this is a plain new
     table with two ordinary forward FKs to already-existing tables
     (`roles.id`, `users.id`) and no circular dependency -- `Base.metadata
     .create_all` creates it for free on both SQLite and a fresh Postgres,
     and on an already-deployed Postgres database (existing `roles`/`users`
     rows, new table has zero rows to backfill). No `ensure_schema_migrations`
     step exists (or is needed) for it -- verified empirically against a real
     local Postgres 16 and SQLite, not just reasoned; see
     docs/design/custom-roles-design.md §6.5 (db-admin sign-off) and
     tests/test_migration_role_permission_audit_new_table.py.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _pg_enum_type_names() -> tuple[type, ...]:
    """Import lazily — only ever needed when talking to Postgres, and doing
    it lazily avoids any import-order surprises for SQLite-only setups (the
    class itself is always importable regardless of which DB is in use, but
    there's no reason to pay for it up front)."""
    from sqlalchemy.dialects.postgresql import ENUM as PGEnum

    return (PGEnum,)


def _migrate_users_table(engine: Engine, inspector) -> None:
    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "is_active" not in existing_columns:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE")
            )
            logger.info("Schema migration: added users.is_active")
        if "deactivated_at" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN deactivated_at TIMESTAMP NULL"))
            logger.info("Schema migration: added users.deactivated_at")


def _migrate_tasks_archived_at(engine: Engine, inspector) -> None:
    existing_columns = {col["name"] for col in inspector.get_columns("tasks")}
    if "archived_at" in existing_columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN archived_at TIMESTAMP NULL"))
    logger.info("Schema migration: added tasks.archived_at")


def _migrate_tasks_category_priority_to_string(engine: Engine, inspector) -> None:
    """Postgres-only: convert `tasks.category`/`tasks.priority` from their
    original native `Enum(TaskCategory)`/`Enum(TaskPriority)` columns to
    plain `VARCHAR`, per docs/design/custom-fields-admin-design.md §2.3.

    Verified against a real Postgres 16 table with existing rows (not just
    an empty one): SQLAlchemy's generic `Enum` type persists a Python
    str-Enum member's *name* at the DB level (e.g. `'MEETING'`), not its
    lowercase `.value` (`'meeting'`) — the same convention already relied on
    elsewhere in this codebase (see the comment on
    `TimeEntry.__table_args__`). Every `TaskCategory`/`TaskPriority` member
    in this app happens to satisfy `name.lower() == value` by construction,
    so `USING lower(category::text)` recovers exactly the string the new
    plain-`String` column and `DropdownOption.value` rows expect — a plain
    `::text` cast alone would silently leave every existing task's
    category/priority stuck in the old upper-cased, non-matching form.
    """
    if engine.dialect.name != "postgresql":
        return

    pg_enum_types = _pg_enum_type_names()
    columns = {col["name"]: col for col in inspector.get_columns("tasks")}

    with engine.begin() as conn:
        category_col = columns.get("category")
        if category_col is not None and isinstance(category_col["type"], pg_enum_types):
            conn.execute(
                text("ALTER TABLE tasks ALTER COLUMN category TYPE VARCHAR USING lower(category::text)")
            )
            logger.info("Schema migration: converted tasks.category from native enum to VARCHAR")

        priority_col = columns.get("priority")
        if priority_col is not None and isinstance(priority_col["type"], pg_enum_types):
            conn.execute(
                text("ALTER TABLE tasks ALTER COLUMN priority TYPE VARCHAR USING lower(priority::text)")
            )
            logger.info("Schema migration: converted tasks.priority from native enum to VARCHAR")


def _migrate_custom_field_options_to_dropdown_options(engine: Engine, inspector) -> None:
    """One-time data migration: copy `custom_field_definitions.options` CSV
    values into `dropdown_options` rows (`scope=custom_field`), then drop the
    now-unused column. Presence of the `options` column is both the trigger
    *and* the idempotency guard — once dropped, a second run sees no column
    and no-ops, so this only ever runs once per database.

    Must run after `Base.metadata.create_all` (so `dropdown_options` already
    exists to insert into) — `app/main.py`'s lifespan already calls this
    function after `create_all`.
    """
    existing_columns = {col["name"] for col in inspector.get_columns("custom_field_definitions")}
    if "options" not in existing_columns:
        return

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, options FROM custom_field_definitions")).fetchall()
        migrated = 0
        for field_id, options_csv in rows:
            if not options_csv:
                continue
            values = [v.strip() for v in options_csv.split(",") if v.strip()]
            for position, value in enumerate(values):
                conn.execute(
                    text(
                        """
                        INSERT INTO dropdown_options
                            (id, scope, custom_field_id, value, label, is_builtin, is_active, position, created_at)
                        VALUES
                            (:id, :scope, :field_id, :value, :label, :is_builtin, :is_active, :position, :created_at)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        # DropdownOption.scope is an Enum(DropdownOptionScope)
                        # column — same "stores the member's .name" convention
                        # as tasks.category/priority did (see module docstring).
                        "scope": "CUSTOM_FIELD",
                        "field_id": field_id,
                        "value": value,
                        "label": value,
                        "is_builtin": False,
                        "is_active": True,
                        "position": position,
                        "created_at": datetime.utcnow(),
                    },
                )
                migrated += 1

        conn.execute(text("ALTER TABLE custom_field_definitions DROP COLUMN options"))

    logger.info(
        "Schema migration: migrated %d custom_field_definitions.options value(s) into "
        "dropdown_options and dropped the options column",
        migrated,
    )


def _migrate_org_structure_backfill(engine: Engine, inspector) -> None:
    """Round A (Department -> Team org structure): `departments`/`teams`
    themselves are brand-new tables, already created by `Base.metadata.create_all`
    (called before this function, per `app/main.py`'s lifespan — same
    precondition `_migrate_custom_field_options_to_dropdown_options` above
    already relies on for `dropdown_options`). This function's job is
    exclusively the two things `create_all` can't do:

      1. Seed exactly one bootstrap Department + Team, both named "General"
         (`Team.manager_id` left null), the first time this ever runs.
      2. Add `users.team_id` / `tasks.team_id` to a database that predates
         those columns, backfilling every *pre-existing* row in the same
         pass so nothing's board looks any different on deploy.

    Deliberately NOT keyed on `WHERE team_id IS NULL`: a null `team_id` is a
    legitimate, *permanent* state going forward (an unplaced new hire, or a
    task/user an admin has deliberately left unassigned), not merely a
    not-yet-migrated marker. This function is called on every app startup —
    if the backfill were data-keyed (`UPDATE ... WHERE team_id IS NULL`)
    instead of schema-keyed, every single restart would silently drag any
    such intentionally-unassigned row back onto "General", which is exactly
    the "reasoned my way past it instead of checking" failure mode this
    project already had one near-miss with (see module docstring). Instead,
    whether to backfill a table is decided once, from whether the column
    itself existed *before* this call (schema state, not data state) — the
    same idempotency idiom `_migrate_custom_field_options_to_dropdown_options`
    already uses. Once a table's `team_id` column has been added and
    backfilled, this function never issues another UPDATE against it again,
    on any subsequent startup, no matter what value any row holds by then.

    Bootstrap Department/Team creation itself uses a `SELECT ... WHERE
    name = 'General'` existence check (not schema state) since there's no
    column/table-presence signal available for it the way there is for the
    column backfills — safe here specifically because inserting a row is
    naturally idempotent-by-name, unlike overwriting one.
    """
    with engine.begin() as conn:
        existing_department = conn.execute(
            text("SELECT id FROM departments WHERE name = :name"), {"name": "General"}
        ).fetchone()
        if existing_department is None:
            general_department_id = str(uuid.uuid4())
            conn.execute(
                text(
                    "INSERT INTO departments (id, name, is_active, created_at) "
                    "VALUES (:id, :name, :is_active, :created_at)"
                ),
                {
                    "id": general_department_id,
                    "name": "General",
                    "is_active": True,
                    "created_at": datetime.utcnow(),
                },
            )
            logger.info("Schema migration: created bootstrap 'General' department")
        else:
            general_department_id = existing_department[0]

        existing_team = conn.execute(
            text("SELECT id FROM teams WHERE department_id = :dept_id AND name = :name"),
            {"dept_id": general_department_id, "name": "General"},
        ).fetchone()
        if existing_team is None:
            general_team_id = str(uuid.uuid4())
            now = datetime.utcnow()
            conn.execute(
                text(
                    "INSERT INTO teams "
                    "(id, department_id, name, manager_id, is_active, created_at, updated_at) "
                    "VALUES (:id, :department_id, :name, NULL, :is_active, :created_at, :updated_at)"
                ),
                {
                    "id": general_team_id,
                    "department_id": general_department_id,
                    "name": "General",
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            logger.info("Schema migration: created bootstrap 'General' team")
        else:
            general_team_id = existing_team[0]

    users_columns = {col["name"] for col in inspector.get_columns("users")}
    if "team_id" not in users_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN team_id VARCHAR NULL REFERENCES teams(id)"))
            conn.execute(text("UPDATE users SET team_id = :team_id"), {"team_id": general_team_id})
        logger.info(
            "Schema migration: added users.team_id and backfilled existing users onto 'General'"
        )

    tasks_columns = {col["name"] for col in inspector.get_columns("tasks")}
    if "team_id" not in tasks_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN team_id VARCHAR NULL REFERENCES teams(id)"))
            conn.execute(text("UPDATE tasks SET team_id = :team_id"), {"team_id": general_team_id})
        logger.info(
            "Schema migration: added tasks.team_id and backfilled existing tasks onto 'General'"
        )


def _migrate_rbac_schema_backfill(engine: Engine, inspector) -> None:
    """RBAC Round B1 (additive schema only): `roles` / `role_permissions`
    are brand-new tables, already created by `Base.metadata.create_all`
    (called before this function, same precondition as
    `_migrate_org_structure_backfill` relies on for `departments`/`teams`).
    This function's job:

      1. Seed exactly 3 builtin `Role` rows (key: "employee"/"manager"/
         "admin"), idempotent via a per-key `SELECT ... WHERE key = ...`
         existence check -- safe to re-run every startup since inserting a
         row is naturally idempotent-by-key, same reasoning
         `_migrate_org_structure_backfill` already applies to the "General"
         department/team.
      2. Add `users.role_id` to a database that predates it, via the same
         "ALTER TABLE ADD COLUMN if not in `inspector.get_columns`" pattern
         already used for `users.team_id`.
      3. Backfill `users.role_id` from the legacy `users.role` enum column.

    Comparison verified empirically against real Postgres 16 (not reasoned
    from first principles -- this project has a documented near-miss for
    exactly that shortcut, see module docstring): a user inserted with
    `role=UserRole.EMPLOYEE` stores the raw value `'EMPLOYEE'` in the
    `users.role` column (the enum member's `.name`, not its lowercase
    `.value` -- the same convention already relied on for
    `tasks.category`/`tasks.priority` before their own migration, and for
    `TimeEntry.status` in `TimeEntry.__table_args__`). Confirmed on both
    backends: SQLite stores the same uppercase string (no real native enum
    type there either); on Postgres, comparing the native `userrole` enum
    column against a *mismatched-case* bind parameter (e.g. `'employee'`)
    doesn't silently fail to match -- it raises
    `InvalidTextRepresentation` immediately, because Postgres attempts an
    implicit cast of the literal to the enum type before comparing. That
    fail-loud behavior is exactly why the three `UPDATE ... WHERE role =
    :enum_name` statements below use the literal uppercase member names
    ('EMPLOYEE'/'MANAGER'/'ADMIN') rather than `key.upper()` string-munging
    or a `::text` cast -- if a future enum member's name and key ever
    diverged, this would error loudly on that backend instead of silently
    mismatching everyone onto no role.

    Unlike step 5's `users.team_id` (see `_migrate_org_structure_backfill`'s
    docstring), this backfill is deliberately kept **data-state gated**
    (`WHERE role_id IS NULL`) rather than schema-state gated, and re-runs on
    every startup indefinitely -- the opposite choice, made deliberately,
    not a copy-paste of that shape:

      - `team_id = NULL` is a legitimate, permanent, *admin-chosen* state
        (an intentionally unplaced hire) that a data-gated re-fire would
        silently stomp back onto "General" -- that's what made a
        data-state gate wrong there.
      - `role_id = NULL` has no such standing meaning in this round. Every
        user always has exactly one non-null `role`; nothing in this round
        (or before it) ever writes `role_id` at all -- that's B2's job, out
        of scope here. So *every* row with `role_id IS NULL` at any point
        during B1's bake period is purely an artifact of timing (created
        before this migration ran, or created via the still-unmodified
        legacy user-creation path sometime after), never an intentional
        choice. Leaving such rows permanently unbackfilled (mirroring
        step 5's shape) would let stragglers created between this deploy
        and B2's cutover silently reach B2 with a null `role_id`, which is
        exactly the kind of gap this round exists to close before the
        higher-risk cutover lands. Re-checking `WHERE role_id IS NULL` on
        every startup costs three cheap indexed-by-nothing UPDATEs against
        rows that already all have `role_id` set (a no-op scan) once the
        database is caught up, and self-heals any straggler in the
        meantime -- see
        test_migration_rbac_schema_with_real_data.py for the regression
        test proving both the idempotency and the self-healing behavior.
    """
    builtin_roles = (
        ("employee", "Employee", "EMPLOYEE"),
        ("manager", "Manager", "MANAGER"),
        ("admin", "Admin", "ADMIN"),
    )

    role_ids: dict[str, str] = {}
    with engine.begin() as conn:
        for key, name, _enum_name in builtin_roles:
            existing_role = conn.execute(
                text("SELECT id FROM roles WHERE key = :key"), {"key": key}
            ).fetchone()
            if existing_role is None:
                new_role_id = str(uuid.uuid4())
                conn.execute(
                    text(
                        "INSERT INTO roles (id, key, name, is_builtin, created_at) "
                        "VALUES (:id, :key, :name, :is_builtin, :created_at)"
                    ),
                    {
                        "id": new_role_id,
                        "key": key,
                        "name": name,
                        "is_builtin": True,
                        "created_at": datetime.utcnow(),
                    },
                )
                role_ids[key] = new_role_id
                logger.info("Schema migration: seeded builtin role %r", key)
            else:
                role_ids[key] = existing_role[0]

    users_columns = {col["name"] for col in inspector.get_columns("users")}
    if "role_id" not in users_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN role_id VARCHAR NULL REFERENCES roles(id)"))
        logger.info("Schema migration: added users.role_id")

    with engine.begin() as conn:
        for key, _name, enum_name in builtin_roles:
            conn.execute(
                text(
                    "UPDATE users SET role_id = :role_id "
                    "WHERE role_id IS NULL AND role = :enum_name"
                ),
                {"role_id": role_ids[key], "enum_name": enum_name},
            )


def _rebuild_sqlite_users_table_role_nullable(engine: Engine, inspector) -> None:
    """SQLite has no `ALTER TABLE ... ALTER COLUMN`, so making one column
    nullable means the standard rebuild dance: create a new table with the
    desired shape, copy every row, drop the old table, rename the new one
    into place — all inside one transaction, so a crash mid-way can't leave
    the database in a headless in-between state (no `users` table at all,
    or two of them).

    The new table's column list, primary key, and foreign keys are all
    derived from `inspector.get_columns("users")` /
    `get_pk_constraint("users")` / `get_foreign_keys("users")` — i.e. from
    whatever `users` *actually* looks like right now — rather than
    hand-copied from `models.py`, specifically so this function doesn't need
    updating (or silently drift out of sync) the next time a future round
    adds a column to `User`. Only `role`'s nullability is overridden from
    what's reflected; everything else is carried through verbatim.

    Foreign keys pointing *at* `users.id` from other tables
    (`teams.manager_id`, `tasks.assignee_id`/`created_by_id`,
    `time_entries.user_id`, `task_comments.author_id`,
    `task_audit_entries.actor_id`, `task_status_events.changed_by_id`, ...)
    are unaffected by this rebuild: SQLite stores a FK constraint as literal
    DDL text embedded in the *referencing* table's own `CREATE TABLE`
    statement, not as a live pointer resolved against the referenced table's
    identity — dropping and recreating `users` (same name, same row `id`
    values, copied verbatim by the `INSERT INTO ... SELECT` below) never
    touches those other tables' own DDL or rows at all. Confirmed
    empirically, not assumed — see
    `tests/test_migration_users_role_nullable_with_real_data.py`, which
    builds exactly this cross-referencing shape (a team with a manager, a
    task with an assignee and a creator, a time entry) on SQLite, runs this
    rebuild, and asserts every one of those references still resolves to
    the same row afterward. This is also consistent with `models.py`'s own
    note on `Team.manager_id` — SQLite "never validates FK targets at
    `CREATE TABLE`/DDL time regardless" — and with this project already
    running with FK enforcement off everywhere (no `PRAGMA
    foreign_keys=ON`).

    Indexes are handled explicitly because they don't ride along with
    `ALTER TABLE ... RENAME TO`'s row data the way columns/constraints
    baked into `CREATE TABLE` do: SQLite drops a table's indexes when the
    table itself is dropped, so every index reflected by
    `inspector.get_indexes("users")` (already excludes the PK's own
    implicit `sqlite_autoindex_*`, which is recreated automatically by the
    `PRIMARY KEY` clause in the new `CREATE TABLE`) is recreated by name
    after the rename, preserving uniqueness — e.g. `ix_users_email`.
    """
    table_name = "users"
    tmp_name = "users__role_nullable_rebuild"

    columns = inspector.get_columns(table_name)
    pk = inspector.get_pk_constraint(table_name)
    fks = inspector.get_foreign_keys(table_name)
    indexes = inspector.get_indexes(table_name)

    column_names = [col["name"] for col in columns]

    col_defs = []
    for col in columns:
        name = col["name"]
        type_str = col["type"].compile(dialect=engine.dialect)
        nullable = True if name == "role" else col["nullable"]
        clause = f'"{name}" {type_str}' + ("" if nullable else " NOT NULL")
        col_defs.append(clause)

    pk_cols = pk.get("constrained_columns") or []
    if pk_cols:
        col_defs.append("PRIMARY KEY (" + ", ".join(f'"{c}"' for c in pk_cols) + ")")

    for fk in fks:
        local_cols = ", ".join(f'"{c}"' for c in fk["constrained_columns"])
        referred_cols = ", ".join(f'"{c}"' for c in fk["referred_columns"])
        col_defs.append(
            f'FOREIGN KEY({local_cols}) REFERENCES "{fk["referred_table"]}" ({referred_cols})'
        )

    create_sql = f'CREATE TABLE "{tmp_name}" (\n  ' + ",\n  ".join(col_defs) + "\n)"
    quoted_cols = ", ".join(f'"{c}"' for c in column_names)

    with engine.begin() as conn:
        conn.execute(text(create_sql))
        conn.execute(
            text(
                f'INSERT INTO "{tmp_name}" ({quoted_cols}) '
                f'SELECT {quoted_cols} FROM "{table_name}"'
            )
        )
        conn.execute(text(f'DROP TABLE "{table_name}"'))
        conn.execute(text(f'ALTER TABLE "{tmp_name}" RENAME TO "{table_name}"'))

        for idx in indexes:
            idx_cols = ", ".join(f'"{c}"' for c in idx["column_names"])
            unique_kw = "UNIQUE " if idx.get("unique") else ""
            conn.execute(
                text(f'CREATE {unique_kw}INDEX "{idx["name"]}" ON "{table_name}" ({idx_cols})')
            )


def _migrate_users_role_nullable(engine: Engine, inspector) -> None:
    """RBAC Round B2 (schema half): make `users.role` nullable on an
    already-deployed database. See the module docstring (step 7) for the
    "why" (Round B3's custom roles have no valid `UserRole` member to hold
    `role` at).

    Idempotency guard, both backends: `inspector.get_columns("users")`'s
    `role` entry's own `nullable` flag. If it's already `True`, this is a
    pure no-op — safe to call on every startup indefinitely, the same
    "inspect before acting" rule every other step in this module follows.
    Purely a nullability change: no row's `role` *value* is touched by
    either branch below, on either backend.

    --- Rollback plan (written before shipping, not after) -----------------

    If something is wrong with the new nullable-role/custom-role system
    after this ships, reverting is **not symmetric** between backends:

      * Postgres: `role` isn't dropped by this migration, so rolling the
        *application* back to a version that only ever reads/writes
        `user.role` directly (never `role_id`) works immediately, with no
        further DB action required — `NULL` is just a value the (already
        nullable) column can hold; a rolled-back app that never writes NULL
        there again simply never produces one going forward. Re-tightening
        the column back to `NOT NULL` is not required for this rollback to
        work, and — see the SQLite case below — isn't safe to do blindly.

      * SQLite: the column is already nullable post-migration (and, from
        this round on, in `Base.metadata.create_all`'s own fresh-DB shape
        too, since `models.py`'s `User.role` itself is now `nullable=True`).
        Rebuilding it back to `NOT NULL` — the same create-copy-drop-rename
        dance, run in reverse — would **fail outright** the moment any row
        already has `role IS NULL`, because the copy step's `INSERT INTO
        ... SELECT` would itself violate the rebuilt table's `NOT NULL`
        constraint. Round B3 assigning a custom role to even a single user
        is exactly what produces such a row. So: a schema-level rollback of
        *this* migration is only mechanically possible before any custom
        role has ever been assigned to anyone — once B3 is in real use,
        reversing the nullability is a data-loss-shaped operation (every
        custom-role user's `role` would first need to be invented or
        nulled-out-then-backfilled some other way), not a mechanical schema
        revert.

      This asymmetry is a direct consequence of SQLite never having had a
      real `ALTER COLUMN`. Operationally, the safe rollback story on either
      backend is "stop assigning/using custom roles going forward" (an
      application-level rollback), never "un-relax the nullability" (a
      schema-level rollback) — this migration is a deliberate one-way door
      at the schema level, even though it's a no-op / harmless in the
      Postgres case specifically.
    """
    columns = {col["name"]: col for col in inspector.get_columns("users")}
    role_col = columns.get("role")
    if role_col is None or role_col["nullable"]:
        return

    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ALTER COLUMN role DROP NOT NULL"))
        logger.info("Schema migration: relaxed users.role to nullable (Postgres DROP NOT NULL)")
    elif engine.dialect.name == "sqlite":
        _rebuild_sqlite_users_table_role_nullable(engine, inspector)
        logger.info("Schema migration: relaxed users.role to nullable (SQLite table rebuild)")
    else:  # pragma: no cover - project only ever targets these two dialects
        raise NotImplementedError(
            f"users.role nullable migration not implemented for dialect {engine.dialect.name!r}"
        )


def _migrate_manual_time_entry_columns(engine: Engine, inspector) -> None:
    """Manual/retroactive time-logging feature (schema only, additive):

      - `tasks.is_manual_entry` BOOLEAN NOT NULL DEFAULT FALSE
      - `tasks.started_at` TIMESTAMP NULL
      - `time_entries.is_manual` BOOLEAN NOT NULL DEFAULT FALSE

    No backfill is needed for any of the three: a pre-existing row landing
    on `is_manual_entry=False` / `is_manual=False` / `started_at=NULL` is
    exactly correct (no historical task or time entry was ever manually
    logged), not merely a placeholder. Standard idempotent
    `inspector.get_columns` guard, same as every other additive column in
    this module -- safe on both backends, safe to call on every startup.
    """
    task_columns = {col["name"] for col in inspector.get_columns("tasks")}
    with engine.begin() as conn:
        if "is_manual_entry" not in task_columns:
            conn.execute(
                text("ALTER TABLE tasks ADD COLUMN is_manual_entry BOOLEAN NOT NULL DEFAULT FALSE")
            )
            logger.info("Schema migration: added tasks.is_manual_entry")
        if "started_at" not in task_columns:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN started_at TIMESTAMP NULL"))
            logger.info("Schema migration: added tasks.started_at")

    time_entry_columns = {col["name"] for col in inspector.get_columns("time_entries")}
    if "is_manual" not in time_entry_columns:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE time_entries ADD COLUMN is_manual BOOLEAN NOT NULL DEFAULT FALSE")
            )
        logger.info("Schema migration: added time_entries.is_manual")


def _migrate_audit_action_add_manual_time_logged(engine: Engine, inspector) -> None:
    """Postgres-only: `task_audit_entries.action` is a *native* Postgres
    `ENUM` type (`Enum(AuditAction)` in models.py never sets
    `native_enum=False`) -- confirmed empirically, not assumed, against a
    real local Postgres 16 database (`inspector.get_columns("task_audit_entries")`
    reflects the `action` column's type as `sqlalchemy.dialects.postgresql
    .named_types.ENUM`, and the type `auditaction` shows up in `pg_type`
    with `typtype = 'e'`). Adding a new Python-side `AuditAction` member
    (`MANUAL_TIME_LOGGED`) is therefore a real, migration-relevant DDL
    operation on Postgres -- `ALTER TYPE auditaction ADD VALUE` -- unlike
    SQLite, which has no real native enum type at the DB level for this
    column at all (nothing to do there; a plain string column accepts any
    value already).

    `ADD VALUE IF NOT EXISTS` (supported since Postgres 9.6) makes this
    naturally idempotent -- safe to run on every startup, including against
    a database that already has this value from a previous run. Verified
    directly against real Postgres 16: `ALTER TYPE ... ADD VALUE IF NOT
    EXISTS` runs successfully inside a transaction (supported since Postgres
    12; this project targets 16), runs a second time with no error, and a
    `TaskAuditEntry` row can be inserted with `action='MANUAL_TIME_LOGGED'`
    afterward -- see test_migration_manual_time_entry_with_real_data.py.
    """
    if engine.dialect.name != "postgresql":
        return

    columns = {col["name"]: col for col in inspector.get_columns("task_audit_entries")}
    action_col = columns.get("action")
    if action_col is None or not isinstance(action_col["type"], _pg_enum_type_names()):
        # Either the table doesn't exist yet on this call (guarded by the
        # caller) or `action` is no longer a native enum (e.g. some future
        # round converts it to a plain string, the way `tasks.category`/
        # `tasks.priority` already were) -- nothing to do in either case.
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'MANUAL_TIME_LOGGED'"))
    logger.info("Schema migration: added 'MANUAL_TIME_LOGGED' to the Postgres auditaction enum type")


def ensure_schema_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "users" in table_names:
        _migrate_users_table(engine, inspector)

    if "tasks" in table_names:
        _migrate_tasks_archived_at(engine, inspector)
        # Re-inspect: the archived_at ADD COLUMN above happened on a raw
        # connection, not through this cached inspector, so its own
        # get_columns("tasks") cache is unaffected — but re-fetching here
        # keeps this function correct even if that changes later, and the
        # cost is one extra reflection query at startup.
        inspector = inspect(engine)
        _migrate_tasks_category_priority_to_string(engine, inspector)

    if "custom_field_definitions" in table_names:
        _migrate_custom_field_options_to_dropdown_options(engine, inspector)

    if {"departments", "teams", "users", "tasks"} <= table_names:
        _migrate_org_structure_backfill(engine, inspector)

    if {"roles", "role_permissions", "users"} <= table_names:
        _migrate_rbac_schema_backfill(engine, inspector)

    if "users" in table_names:
        # Unconditional re-inspect, *not* nested inside the `roles`/
        # `role_permissions` block above: `_migrate_users_role_nullable`
        # (specifically the SQLite rebuild path) derives its new table's
        # entire column list from this inspector, so it must see every
        # `ALTER TABLE users ADD COLUMN ...` issued by *any* earlier step in
        # this function (`_migrate_users_table`'s `is_active`/
        # `deactivated_at`, `_migrate_org_structure_backfill`'s `team_id`,
        # `_migrate_rbac_schema_backfill`'s `role_id`) via a raw connection,
        # none of which this cached `inspector` object picks up on its own.
        # Nesting this re-inspect inside a conditional that can be skipped
        # (e.g. a database that has `users` but not yet `roles`/
        # `role_permissions`) was tried and caught by
        # test_bootstrap_and_migrations.py::test_ensure_schema_migrations_adds_missing_columns
        # during this round's own verification: it silently dropped
        # `is_active`/`deactivated_at` from the rebuilt SQLite table because
        # the stale inspector never reflected them — exactly the kind of
        # thing this project's near-miss (see module docstring) exists to
        # keep from shipping unverified again.
        inspector = inspect(engine)
        _migrate_users_role_nullable(engine, inspector)

    if {"tasks", "time_entries"} <= table_names:
        _migrate_manual_time_entry_columns(engine, inspector)

    if "task_audit_entries" in table_names:
        # Re-inspect: needs to see task_audit_entries as it exists right now
        # (this table is untouched by every migration step above, but a
        # fresh inspector call here keeps this step correct/self-contained
        # regardless of ordering changes elsewhere in this function).
        inspector = inspect(engine)
        _migrate_audit_action_add_manual_time_logged(engine, inspector)
