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
