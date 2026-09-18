"""RBAC Round B2 (schema half): `users.role` relaxed from `NOT NULL` to
nullable — verified against real inserted data on **both** backends, not
just Postgres like every prior migration-round test file.

That split matters here specifically: on Postgres this migration is a
one-line `ALTER TABLE users ALTER COLUMN role DROP NOT NULL`
(`app/services/migrations.py::_migrate_users_role_nullable`), but SQLite has
no `ALTER COLUMN` at all, so the same nullability change there means a full
create-copy-drop-rename table rebuild
(`_rebuild_sqlite_users_table_role_nullable`) — real complexity with real
ways to lose data, orphan a foreign key, or silently drop an index. This
file exercises the SQLite path with the same rigor
`test_migration_old_schema_with_real_data.py` and friends already apply on
Postgres: build the *old* (pre-migration) shape by hand with real
cross-referencing data (a team with a manager, a task with an assignee and a
creator, a time entry), run the actual migration function, assert the raw
post-migration values directly (not just "no exception was thrown"), then
run it again to prove idempotency.

Simulates an already-deployed database at *today's* shape (i.e. already past
every prior round, including Round B1's `roles`/`role_permissions`/
`users.role_id`) but from *before* this round: `users.role` is still
`NOT NULL`.
"""

import os
import uuid
from datetime import datetime

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.environ.get(
    "MIGRATION_TEST_POSTGRES_URL",
    "postgresql://app_user:app_password@localhost:5432/time_tracking",
)
SCHEMA = "migration_test_role_nullable_b2"


def _maintenance_engine():
    return create_engine(POSTGRES_URL)


def _build_pre_b2_schema(metadata):
    """Hand-build `departments`/`teams`/`roles`/`role_permissions`/`users`/
    `tasks`/`time_entries` exactly as they exist today, right before this
    round: every prior migration already applied (Round A's org structure,
    Round B1's RBAC additive schema) but `users.role` is still `NOT NULL`.
    Uses SQLAlchemy Core (a separate `MetaData`, not `app.database.Base`) so
    this is independent of whatever the current app models look like — same
    technique the other `test_migration_*_with_real_data.py` files use.
    """
    from app.models import UserRole

    departments = Table(
        "departments",
        metadata,
        Column("id", String, primary_key=True),
        Column("name", String, nullable=False, unique=True),
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
        Column("created_at", DateTime),
    )

    teams = Table(
        "teams",
        metadata,
        Column("id", String, primary_key=True),
        Column("department_id", ForeignKey("departments.id"), nullable=False),
        Column("name", String, nullable=False),
        Column("manager_id", ForeignKey("users.id"), nullable=True),
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
    )

    roles = Table(
        "roles",
        metadata,
        Column("id", String, primary_key=True),
        Column("key", String, nullable=False, unique=True),
        Column("name", String, nullable=False),
        Column("is_builtin", Boolean, nullable=False, server_default=text("true")),
        Column("created_at", DateTime),
    )

    users = Table(
        "users",
        metadata,
        Column("id", String, primary_key=True),
        Column("email", String, nullable=False, unique=True),
        Column("full_name", String, nullable=False),
        Column("hashed_password", String, nullable=False),
        Column("role", Enum(UserRole), nullable=False),  # <-- pre-B2: NOT NULL
        Column("manager_id", ForeignKey("users.id"), nullable=True),
        Column("team_id", ForeignKey("teams.id"), nullable=True),
        Column("role_id", ForeignKey("roles.id"), nullable=True),
        Column("created_at", DateTime),
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
        Column("deactivated_at", DateTime, nullable=True),
    )

    tasks = Table(
        "tasks",
        metadata,
        Column("id", String, primary_key=True),
        Column("project_id", String, nullable=True),
        Column("assignee_id", ForeignKey("users.id"), nullable=True),
        Column("created_by_id", ForeignKey("users.id"), nullable=False),
        Column("team_id", ForeignKey("teams.id"), nullable=True),
        Column("title", String, nullable=False),
        Column("description", Text, nullable=True),
        Column("task_type", String, nullable=False, server_default="normal"),
        Column("category", String, nullable=False),
        Column("category_other_text", String, nullable=True),
        Column("priority", String, nullable=False, server_default="normal"),
        Column("status", String, nullable=False, server_default="backlog"),
        Column("position", String, nullable=False, server_default="0"),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
    )

    time_entries = Table(
        "time_entries",
        metadata,
        Column("id", String, primary_key=True),
        Column("task_id", ForeignKey("tasks.id"), nullable=False),
        Column("user_id", ForeignKey("users.id"), nullable=False),
        Column("status", String, nullable=False, server_default="RUNNING"),
        Column("started_at", DateTime),
        Column("last_resumed_at", DateTime, nullable=True),
        Column("accumulated_seconds", Float, nullable=False, server_default="0"),
        Column("ended_at", DateTime, nullable=True),
    )

    return departments, teams, roles, users, tasks, time_entries


def _seed_real_data(engine, tables):
    """Insert one department/team/3 users (admin/manager/employee, with
    manager and team-membership cross-references), one task, and one time
    entry — real, mutually-referencing rows, not an isolated `users` table
    in a vacuum."""
    from app.core.security import hash_password
    from app.models import UserRole

    departments, teams, roles, users, tasks, time_entries = tables

    dept_id = str(uuid.uuid4())
    team_id = str(uuid.uuid4())
    admin_id = str(uuid.uuid4())
    manager_id = str(uuid.uuid4())
    employee_id = str(uuid.uuid4())
    role_admin_id = str(uuid.uuid4())
    role_manager_id = str(uuid.uuid4())
    role_employee_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    entry_id = str(uuid.uuid4())
    now = datetime.utcnow()

    with engine.begin() as conn:
        conn.execute(
            departments.insert(),
            {"id": dept_id, "name": "Engineering", "is_active": True, "created_at": now},
        )
        conn.execute(
            teams.insert(),
            {
                "id": team_id,
                "department_id": dept_id,
                "name": "Backend",
                "manager_id": None,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            roles.insert(),
            [
                {"id": role_admin_id, "key": "admin", "name": "Admin", "is_builtin": True, "created_at": now},
                {"id": role_manager_id, "key": "manager", "name": "Manager", "is_builtin": True, "created_at": now},
                {"id": role_employee_id, "key": "employee", "name": "Employee", "is_builtin": True, "created_at": now},
            ],
        )
        conn.execute(
            users.insert(),
            [
                {
                    "id": admin_id,
                    "email": "b2-admin@example.com",
                    "full_name": "B2 Admin",
                    "hashed_password": hash_password("password123"),
                    "role": UserRole.ADMIN,
                    "manager_id": None,
                    "team_id": None,
                    "role_id": role_admin_id,
                    "created_at": now,
                    "is_active": True,
                    "deactivated_at": None,
                },
                {
                    "id": manager_id,
                    "email": "b2-manager@example.com",
                    "full_name": "B2 Manager",
                    "hashed_password": hash_password("password123"),
                    "role": UserRole.MANAGER,
                    "manager_id": None,
                    "team_id": team_id,
                    "role_id": role_manager_id,
                    "created_at": now,
                    "is_active": True,
                    "deactivated_at": None,
                },
                {
                    "id": employee_id,
                    "email": "b2-employee@example.com",
                    "full_name": "B2 Employee",
                    "hashed_password": hash_password("password123"),
                    "role": UserRole.EMPLOYEE,
                    "manager_id": manager_id,
                    "team_id": team_id,
                    "role_id": role_employee_id,
                    "created_at": now,
                    "is_active": True,
                    "deactivated_at": None,
                },
            ],
        )
        conn.execute(
            teams.update().where(teams.c.id == team_id).values(manager_id=manager_id)
        )
        conn.execute(
            tasks.insert(),
            {
                "id": task_id,
                "assignee_id": employee_id,
                "created_by_id": manager_id,
                "team_id": team_id,
                "title": "Ship the thing",
                "category": "meeting",
                "task_type": "normal",
                "priority": "normal",
                "status": "todo",
                "position": "0",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            time_entries.insert(),
            {
                "id": entry_id,
                "task_id": task_id,
                "user_id": employee_id,
                "status": "PAUSED",
                "started_at": now,
                "last_resumed_at": None,
                "accumulated_seconds": 120.0,
                "ended_at": None,
            },
        )

    return {
        "team_id": team_id,
        "admin_id": admin_id,
        "manager_id": manager_id,
        "employee_id": employee_id,
        "task_id": task_id,
        "entry_id": entry_id,
    }


def _assert_cross_references_intact(engine, ids):
    with engine.connect() as conn:
        team_manager = conn.execute(
            text("SELECT manager_id FROM teams WHERE id = :t"), {"t": ids["team_id"]}
        ).scalar()
        task_row = conn.execute(
            text("SELECT assignee_id, created_by_id, team_id FROM tasks WHERE id = :t"),
            {"t": ids["task_id"]},
        ).fetchone()
        entry_user = conn.execute(
            text("SELECT user_id FROM time_entries WHERE id = :e"), {"e": ids["entry_id"]}
        ).scalar()
        employee_row = conn.execute(
            text("SELECT manager_id, team_id FROM users WHERE id = :u"),
            {"u": ids["employee_id"]},
        ).fetchone()

    assert team_manager == ids["manager_id"]
    assert task_row[0] == ids["employee_id"]
    assert task_row[1] == ids["manager_id"]
    assert task_row[2] == ids["team_id"]
    assert entry_user == ids["employee_id"]
    assert employee_row[0] == ids["manager_id"]
    assert employee_row[1] == ids["team_id"]


# ============================================================================
# Postgres: the one-line ALTER COLUMN path.
# ============================================================================


@pytest.fixture()
def postgres_engine():
    try:
        maint = _maintenance_engine()
        with maint.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Local Postgres not reachable at {POSTGRES_URL}: {exc}")

    with maint.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
    maint.dispose()

    engine = create_engine(POSTGRES_URL, connect_args={"options": f"-c search_path={SCHEMA}"})
    yield engine
    engine.dispose()

    cleanup = _maintenance_engine()
    with cleanup.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
    cleanup.dispose()


def test_migrate_users_role_nullable_postgres_real_data(postgres_engine):
    engine = postgres_engine
    metadata = MetaData()
    tables = _build_pre_b2_schema(metadata)
    metadata.create_all(bind=engine)
    ids = _seed_real_data(engine, tables)

    # ---- Sanity: fixture really does reproduce the pre-B2 shape -----------
    inspector = inspect(engine)
    role_col = {c["name"]: c for c in inspector.get_columns("users")}["role"]
    assert role_col["nullable"] is False

    with engine.connect() as conn:
        pre_roles = dict(conn.execute(text("SELECT id, role FROM users")).fetchall())
    assert pre_roles[ids["admin_id"]] == "ADMIN"
    assert pre_roles[ids["manager_id"]] == "MANAGER"
    assert pre_roles[ids["employee_id"]] == "EMPLOYEE"

    # NOT NULL is really enforced pre-migration.
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, full_name, hashed_password, role, created_at, is_active) "
                    "VALUES (:id, 'pre-null@example.com', 'x', 'x', NULL, now(), true)"
                ),
                {"id": str(uuid.uuid4())},
            )

    # ---- Run the actual migration function (not the whole app's startup ---
    #      sequence -- this file targets this one migration in isolation,
    #      the same way it's actually called from `ensure_schema_migrations`).
    from app.services.migrations import _migrate_users_role_nullable

    _migrate_users_role_nullable(engine, inspector)

    inspector = inspect(engine)
    role_col_after = {c["name"]: c for c in inspector.get_columns("users")}["role"]
    assert role_col_after["nullable"] is True

    with engine.connect() as conn:
        post_roles = dict(conn.execute(text("SELECT id, role FROM users")).fetchall())
    assert post_roles == pre_roles

    _assert_cross_references_intact(engine, ids)

    # ---- Idempotency: running it again must not error or change anything --
    _migrate_users_role_nullable(engine, inspect(engine))
    inspector_twice = inspect(engine)
    assert {c["name"]: c for c in inspector_twice.get_columns("users")}["role"]["nullable"] is True
    with engine.connect() as conn:
        post_roles_twice = dict(conn.execute(text("SELECT id, role FROM users")).fetchall())
    assert post_roles_twice == pre_roles

    # ---- A fresh INSERT with role=NULL now succeeds ------------------------
    new_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, full_name, hashed_password, role, created_at, is_active) "
                "VALUES (:id, 'post-null@example.com', 'x', 'x', NULL, now(), true)"
            ),
            {"id": new_id},
        )
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT role FROM users WHERE id = :id"), {"id": new_id}
        ).scalar()
    assert stored is None


def test_migrate_users_role_nullable_postgres_information_schema_confirms(postgres_engine):
    """Cross-check via `information_schema.columns` directly, independent of
    SQLAlchemy's own reflection, per the project's standing rule to prove a
    migration against the real schema state, not just trust one code path's
    interpretation of it."""
    engine = postgres_engine
    metadata = MetaData()
    tables = _build_pre_b2_schema(metadata)
    metadata.create_all(bind=engine)
    _seed_real_data(engine, tables)

    with engine.connect() as conn:
        pre_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                f"WHERE table_schema = '{SCHEMA}' AND table_name = 'users' AND column_name = 'role'"
            )
        ).scalar()
    assert pre_nullable == "NO"

    from app.services.migrations import _migrate_users_role_nullable

    _migrate_users_role_nullable(engine, inspect(engine))

    with engine.connect() as conn:
        post_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                f"WHERE table_schema = '{SCHEMA}' AND table_name = 'users' AND column_name = 'role'"
            )
        ).scalar()
    assert post_nullable == "YES"


# ============================================================================
# SQLite: the create-copy-drop-rename rebuild path -- the actually risky one.
# ============================================================================


@pytest.fixture()
def sqlite_engine(tmp_path):
    # A real file-backed engine (not the shared in-memory app fixture) so
    # this test owns its schema outright and can hand-build the exact
    # pre-migration shape independent of `app.database`/conftest's own
    # engine setup.
    db_path = tmp_path / "role_nullable_b2.db"
    engine = create_engine(f"sqlite:///{db_path}")
    yield engine
    engine.dispose()


def test_migrate_users_role_nullable_sqlite_real_data(sqlite_engine):
    engine = sqlite_engine
    metadata = MetaData()
    tables = _build_pre_b2_schema(metadata)
    metadata.create_all(bind=engine)
    ids = _seed_real_data(engine, tables)

    # ---- Sanity: fixture really does reproduce the pre-B2 shape -----------
    inspector = inspect(engine)
    role_col = {c["name"]: c for c in inspector.get_columns("users")}["role"]
    assert role_col["nullable"] is False

    email_indexes_before = {i["name"] for i in inspector.get_indexes("users")}
    assert "ix_users_email" not in email_indexes_before  # Core Table above has no explicit index

    with engine.connect() as conn:
        pre_roles = dict(conn.execute(text("SELECT id, role FROM users")).fetchall())
    assert pre_roles[ids["admin_id"]] == "ADMIN"
    assert pre_roles[ids["manager_id"]] == "MANAGER"
    assert pre_roles[ids["employee_id"]] == "EMPLOYEE"

    # NOT NULL is really enforced pre-migration.
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, full_name, hashed_password, role, created_at, is_active) "
                    "VALUES (:id, 'pre-null@example.com', 'x', 'x', NULL, :now, 1)"
                ),
                {"id": str(uuid.uuid4()), "now": datetime.utcnow()},
            )

    # ---- Run the actual migration function (this is the rebuild dance) ----
    from app.services.migrations import _migrate_users_role_nullable

    _migrate_users_role_nullable(engine, inspector)

    inspector = inspect(engine)
    role_col_after = {c["name"]: c for c in inspector.get_columns("users")}["role"]
    assert role_col_after["nullable"] is True

    # ---- Every pre-existing row's `role` value is completely unchanged ----
    with engine.connect() as conn:
        post_roles = dict(conn.execute(text("SELECT id, role FROM users")).fetchall())
    assert post_roles == pre_roles

    # ---- Every other column on every row survived the rebuild verbatim ----
    with engine.connect() as conn:
        employee_row = conn.execute(
            text(
                "SELECT email, full_name, manager_id, team_id, role_id, is_active "
                "FROM users WHERE id = :id"
            ),
            {"id": ids["employee_id"]},
        ).fetchone()
    assert employee_row[0] == "b2-employee@example.com"
    assert employee_row[1] == "B2 Employee"
    assert employee_row[2] == ids["manager_id"]
    assert employee_row[3] == ids["team_id"]
    assert employee_row[4] is not None
    assert employee_row[5] == 1

    # ---- Cross-referencing tables (teams/tasks/time_entries) still --------
    #      resolve to the exact same rows -- proves the rebuild didn't
    #      scramble ids or drop/orphan anything, not just that it "ran".
    _assert_cross_references_intact(engine, ids)

    # ---- A fresh INSERT with role=NULL now succeeds ------------------------
    new_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, full_name, hashed_password, role, created_at, is_active) "
                "VALUES (:id, 'post-null@example.com', 'x', 'x', NULL, :now, 1)"
            ),
            {"id": new_id, "now": datetime.utcnow()},
        )
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT role FROM users WHERE id = :id"), {"id": new_id}
        ).scalar()
    assert stored is None

    # ---- Idempotency: running it again must not error or change anything --
    _migrate_users_role_nullable(engine, inspect(engine))
    inspector_twice = inspect(engine)
    assert {c["name"]: c for c in inspector_twice.get_columns("users")}["role"]["nullable"] is True
    with engine.connect() as conn:
        post_roles_twice = dict(
            conn.execute(text("SELECT id, role FROM users WHERE id != :new"), {"new": new_id}).fetchall()
        )
    assert post_roles_twice == pre_roles
    _assert_cross_references_intact(engine, ids)

    # A third run for good measure -- this migration step's own idempotency
    # guard is schema-state (not data-state) gated, so it should be a
    # complete no-op from the second run onward.
    _migrate_users_role_nullable(engine, inspect(engine))


def test_migrate_users_role_nullable_sqlite_preserves_email_unique_index(sqlite_engine):
    """The rebuild drops and recreates `users` under the hood -- SQLite
    drops a table's indexes along with the table itself, so this proves the
    migration explicitly recreates the unique index on `email` rather than
    silently losing it (which would only surface much later, the first time
    two users happened to collide on an email)."""
    from app.core.security import hash_password
    from app.models import UserRole

    engine = sqlite_engine
    metadata = MetaData()
    departments, teams, roles, users, tasks, time_entries = _build_pre_b2_schema(metadata)
    metadata.create_all(bind=engine)

    with engine.begin() as conn:
        conn.execute(
            text("CREATE UNIQUE INDEX ix_users_email ON users (email)")
        )
        conn.execute(
            users.insert(),
            {
                "id": str(uuid.uuid4()),
                "email": "unique@example.com",
                "full_name": "Someone",
                "hashed_password": hash_password("password123"),
                "role": UserRole.ADMIN,
                "manager_id": None,
                "team_id": None,
                "role_id": None,
                "created_at": datetime.utcnow(),
                "is_active": True,
                "deactivated_at": None,
            },
        )

    inspector = inspect(engine)
    assert "ix_users_email" in {i["name"] for i in inspector.get_indexes("users")}

    from app.services.migrations import _migrate_users_role_nullable

    _migrate_users_role_nullable(engine, inspector)

    inspector_after = inspect(engine)
    indexes_after = {i["name"]: i for i in inspector_after.get_indexes("users")}
    assert "ix_users_email" in indexes_after
    assert indexes_after["ix_users_email"]["unique"] == 1

    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, full_name, hashed_password, role, created_at, is_active) "
                    "VALUES (:id, 'unique@example.com', 'Dup', 'x', NULL, :now, 1)"
                ),
                {"id": str(uuid.uuid4()), "now": datetime.utcnow()},
            )


# ============================================================================
# Full startup sequence (`ensure_schema_migrations`), both backends via the
# app's own `Base` model shape -- confirms this step is correctly wired into
# the real call chain, not just correct in isolation.
# ============================================================================


def test_full_ensure_schema_migrations_relaxes_role_nullable_sqlite(sqlite_engine):
    from app.database import Base
    from app.services.migrations import ensure_schema_migrations

    engine = sqlite_engine
    metadata = MetaData()
    tables = _build_pre_b2_schema(metadata)
    metadata.create_all(bind=engine)
    ids = _seed_real_data(engine, tables)

    Base.metadata.create_all(bind=engine)  # creates any tables this pre-B2 shape is missing
    ensure_schema_migrations(engine)

    inspector = inspect(engine)
    assert {c["name"]: c for c in inspector.get_columns("users")}["role"]["nullable"] is True
    _assert_cross_references_intact(engine, ids)

    with engine.connect() as conn:
        admin_role = conn.execute(
            text("SELECT role FROM users WHERE id = :id"), {"id": ids["admin_id"]}
        ).scalar()
    assert admin_role == "ADMIN"

    # Idempotent as part of the full sequence too.
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)
    inspector_twice = inspect(engine)
    assert {c["name"]: c for c in inspector_twice.get_columns("users")}["role"]["nullable"] is True


def test_full_ensure_schema_migrations_relaxes_role_nullable_postgres(postgres_engine):
    from app.database import Base
    from app.services.migrations import ensure_schema_migrations

    engine = postgres_engine
    metadata = MetaData()
    tables = _build_pre_b2_schema(metadata)
    metadata.create_all(bind=engine)
    ids = _seed_real_data(engine, tables)

    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)

    inspector = inspect(engine)
    assert {c["name"]: c for c in inspector.get_columns("users")}["role"]["nullable"] is True
    _assert_cross_references_intact(engine, ids)

    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)
    inspector_twice = inspect(engine)
    assert {c["name"]: c for c in inspector_twice.get_columns("users")}["role"]["nullable"] is True


# ============================================================================
# The floor: this schema change alone can never null out the sole admin's
# `role`. (The *application*-level guard against a PATCH request doing this
# is covered in tests/test_user_management.py -- these two tests are purely
# about the migration/schema layer never doing it on its own.)
# ============================================================================


def test_sole_admin_role_survives_the_migration_untouched_sqlite(sqlite_engine):
    from app.database import Base
    from app.services.migrations import ensure_schema_migrations

    engine = sqlite_engine
    metadata = MetaData()
    tables = _build_pre_b2_schema(metadata)
    metadata.create_all(bind=engine)
    ids = _seed_real_data(engine, tables)

    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)

    with engine.connect() as conn:
        admin_role = conn.execute(
            text("SELECT role FROM users WHERE id = :id"), {"id": ids["admin_id"]}
        ).scalar()
    assert admin_role == "ADMIN"
    assert admin_role is not None


def test_sole_admin_role_survives_the_migration_untouched_postgres(postgres_engine):
    from app.database import Base
    from app.services.migrations import ensure_schema_migrations

    engine = postgres_engine
    metadata = MetaData()
    tables = _build_pre_b2_schema(metadata)
    metadata.create_all(bind=engine)
    ids = _seed_real_data(engine, tables)

    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)

    with engine.connect() as conn:
        admin_role = conn.execute(
            text("SELECT role FROM users WHERE id = :id"), {"id": ids["admin_id"]}
        ).scalar()
    assert admin_role == "ADMIN"
    assert admin_role is not None
