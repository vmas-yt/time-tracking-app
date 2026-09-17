"""The single most important test in this round: simulate an
already-deployed Postgres database — created under the *old* schema (native
`ENUM` columns for `tasks.category`/`tasks.priority`, a
`custom_field_definitions.options` CSV column, real rows already written
under that shape) — then run this app's exact startup sequence
(`Base.metadata.create_all` -> `ensure_schema_migrations` ->
`ensure_bootstrap_admin` -> `ensure_default_dropdown_options`, in the same
order `app/main.py`'s `lifespan` calls them) against it, and confirm:

  1. Startup completes without error.
  2. Every pre-existing task's category/priority is preserved, correctly
     converted to the new lowercase string form (not the enum member's
     upper-cased *name*, which is what Postgres actually had stored — see
     app/services/migrations.py's module docstring for why a plain `::text`
     cast alone would have been wrong).
  3. Every pre-existing custom field's CSV `options` value migrated into real
     `DropdownOption` rows (`scope=custom_field`), and the old `options`
     column is gone.
  4. The app's normal request path (real API calls, not just direct DB
     queries) serves the migrated data correctly.

This targets a real local Postgres 16 instance — native `ENUM` columns don't
exist on SQLite, so this specific scenario can't be simulated there. Skips
itself if Postgres isn't reachable at MIGRATION_TEST_POSTGRES_URL (defaults
to the local dev instance described in this project's test-running docs).
"""

import os

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
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
SCHEMA = "migration_test_old_schema"


def _maintenance_engine():
    return create_engine(POSTGRES_URL)


@pytest.fixture()
def old_schema_engine():
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


def _build_legacy_schema(engine):
    """Hand-build the tables exactly as they existed before this round's
    model changes: native Enum columns for tasks.category/priority, no
    tasks.archived_at, and a CSV custom_field_definitions.options column.
    Uses SQLAlchemy Core (a separate MetaData, not app.database.Base) so this
    is independent of whatever the current app models look like."""
    from app.models import CustomFieldType, TaskCategory, TaskPriority, TaskStatus, TaskType, UserRole

    metadata = MetaData()

    users = Table(
        "users",
        metadata,
        Column("id", String, primary_key=True),
        Column("email", String, nullable=False, unique=True),
        Column("full_name", String, nullable=False),
        Column("hashed_password", String, nullable=False),
        Column("role", Enum(UserRole), nullable=False),
        Column("manager_id", ForeignKey("users.id"), nullable=True),
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
        Column("title", String, nullable=False),
        Column("description", Text, nullable=True),
        Column("task_type", Enum(TaskType), nullable=False),
        Column("category", Enum(TaskCategory), nullable=False),  # native PG enum
        Column("category_other_text", String, nullable=True),
        Column("priority", Enum(TaskPriority), nullable=False),  # native PG enum
        Column("status", Enum(TaskStatus), nullable=False),
        Column("position", Integer, nullable=True),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
        Column("completed_at", DateTime, nullable=True),
        Column("first_in_progress_at", DateTime, nullable=True),
        # deliberately no archived_at column — that's this round's addition.
    )

    custom_field_definitions = Table(
        "custom_field_definitions",
        metadata,
        Column("id", String, primary_key=True),
        Column("name", String, nullable=False),
        Column("field_type", Enum(CustomFieldType), nullable=False),
        Column("options", String, nullable=True),  # old CSV column
        Column("created_at", DateTime),
    )

    metadata.create_all(bind=engine)
    return users, tasks, custom_field_definitions


def test_migration_preserves_data_from_old_schema(old_schema_engine):
    import uuid
    from datetime import datetime

    from app.core.security import hash_password
    from app.models import CustomFieldType, TaskCategory, TaskPriority, TaskStatus, TaskType, UserRole

    engine = old_schema_engine
    users, tasks, custom_field_definitions = _build_legacy_schema(engine)

    user_id = str(uuid.uuid4())
    task_a_id = str(uuid.uuid4())
    task_b_id = str(uuid.uuid4())
    field_id = str(uuid.uuid4())

    with engine.begin() as conn:
        conn.execute(
            users.insert(),
            {
                "id": user_id,
                "email": "legacy-admin@example.com",
                "full_name": "Legacy Admin",
                "hashed_password": hash_password("password123"),
                "role": UserRole.ADMIN,
                "created_at": datetime.utcnow(),
                "is_active": True,
                "deactivated_at": None,
            },
        )
        conn.execute(
            tasks.insert(),
            [
                {
                    "id": task_a_id,
                    "project_id": None,
                    "assignee_id": user_id,
                    "created_by_id": user_id,
                    "title": "Legacy meeting task",
                    "description": "pre-existing row",
                    "task_type": TaskType.NORMAL,
                    "category": TaskCategory.MEETING,
                    "category_other_text": None,
                    "priority": TaskPriority.EXPEDITE,
                    "status": TaskStatus.BACKLOG,
                    "position": 0,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "completed_at": None,
                    "first_in_progress_at": None,
                },
                {
                    "id": task_b_id,
                    "project_id": None,
                    "assignee_id": user_id,
                    "created_by_id": user_id,
                    "title": "Legacy infra task",
                    "description": None,
                    "task_type": TaskType.AD_HOC,
                    "category": TaskCategory.INFRASTRUCTURE,
                    "category_other_text": None,
                    "priority": TaskPriority.NORMAL,
                    "status": TaskStatus.TODO,
                    "position": 1,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "completed_at": None,
                    "first_in_progress_at": None,
                },
            ],
        )
        conn.execute(
            custom_field_definitions.insert(),
            {
                "id": field_id,
                "name": "Legacy Tag",
                "field_type": CustomFieldType.SELECT,
                "options": "Alpha,Beta,Gamma",
                "created_at": datetime.utcnow(),
            },
        )

    # Sanity check the raw pre-migration values really are the upper-cased
    # enum *names* Postgres stores for a native Enum(TaskCategory) column —
    # confirms the test fixture faithfully reproduces the old schema/data.
    with engine.connect() as conn:
        raw = conn.execute(
            text("SELECT category, priority FROM tasks WHERE id = :id"), {"id": task_a_id}
        ).fetchone()
        assert raw == ("MEETING", "EXPEDITE")

    # ---- Exactly app/main.py's lifespan sequence, in order ----------------
    from app.database import Base
    from app.services.bootstrap import ensure_bootstrap_admin, ensure_default_dropdown_options
    from app.services.migrations import ensure_schema_migrations

    Base.metadata.create_all(bind=engine)  # adds only missing tables (no error on existing ones)
    ensure_schema_migrations(engine)  # the function under test

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        ensure_bootstrap_admin(db)  # no-op: users table is non-empty
        ensure_default_dropdown_options(db)  # seeds into the now-fresh dropdown_options table
    finally:
        db.close()

    # ---- 1. Schema is now correct -----------------------------------------
    inspector = inspect(engine)
    task_columns = {c["name"] for c in inspector.get_columns("tasks")}
    assert "archived_at" in task_columns

    from sqlalchemy.dialects.postgresql import ENUM as PGEnum

    task_column_types = {c["name"]: c["type"] for c in inspector.get_columns("tasks")}
    assert not isinstance(task_column_types["category"], PGEnum)
    assert not isinstance(task_column_types["priority"], PGEnum)

    field_columns = {c["name"] for c in inspector.get_columns("custom_field_definitions")}
    assert "options" not in field_columns

    # ---- 2. Existing task data preserved, correctly cased ------------------
    with engine.connect() as conn:
        rows = {
            row.id: (row.category, row.priority)
            for row in conn.execute(text("SELECT id, category, priority FROM tasks"))
        }
    assert rows[task_a_id] == ("meeting", "expedite")
    assert rows[task_b_id] == ("infrastructure", "normal")

    # And the ORM (now String-typed columns) reads them back correctly too.
    from app.models import Task

    db = SessionLocal()
    try:
        task_a = db.get(Task, task_a_id)
        task_b = db.get(Task, task_b_id)
        assert task_a.category == "meeting"
        assert task_a.priority == "expedite"
        assert task_b.category == "infrastructure"
        assert task_b.priority == "normal"
    finally:
        db.close()

    # ---- 3. Custom field options migrated into dropdown_options -----------
    from app.models import DropdownOption, DropdownOptionScope

    db = SessionLocal()
    try:
        options = (
            db.query(DropdownOption)
            .filter(
                DropdownOption.scope == DropdownOptionScope.CUSTOM_FIELD,
                DropdownOption.custom_field_id == field_id,
            )
            .order_by(DropdownOption.position)
            .all()
        )
        assert [o.value for o in options] == ["Alpha", "Beta", "Gamma"]
        assert all(o.label == o.value for o in options)
        assert all(o.is_builtin is False and o.is_active is True for o in options)

        # Builtin category/priority seed also ran (fresh dropdown_options table).
        categories = (
            db.query(DropdownOption)
            .filter(DropdownOption.scope == DropdownOptionScope.TASK_CATEGORY)
            .all()
        )
        assert any(o.value == "meeting" and o.is_builtin for o in categories)
    finally:
        db.close()

    # ---- 4. Idempotency: running the whole sequence again must not error --
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)
    db = SessionLocal()
    try:
        ensure_bootstrap_admin(db)
        ensure_default_dropdown_options(db)
    finally:
        db.close()

    with engine.connect() as conn:
        rows_again = {
            row.id: (row.category, row.priority)
            for row in conn.execute(text("SELECT id, category, priority FROM tasks"))
        }
    assert rows_again == rows  # unchanged the second time through

    db = SessionLocal()
    try:
        count = (
            db.query(DropdownOption)
            .filter(
                DropdownOption.scope == DropdownOptionScope.CUSTOM_FIELD,
                DropdownOption.custom_field_id == field_id,
            )
            .count()
        )
        assert count == 3  # not duplicated
    finally:
        db.close()

    # ---- 5. The real app, booted against this now-migrated DB, serves it --
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            login = client.post(
                "/auth/login",
                data={"username": "legacy-admin@example.com", "password": "password123"},
            )
            assert login.status_code == 200
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            resp = client.get("/tasks", headers=headers)
            assert resp.status_code == 200
            by_id = {t["id"]: t for t in resp.json()}
            assert by_id[task_a_id]["category"] == "meeting"
            assert by_id[task_a_id]["priority"] == "expedite"
            assert by_id[task_a_id]["total_logged_seconds"] == 0.0
            assert by_id[task_b_id]["category"] == "infrastructure"
            assert by_id[task_b_id]["priority"] == "normal"

            fields = client.get("/admin/custom-fields", headers=headers).json()
            legacy_field = next(f for f in fields if f["id"] == field_id)
            assert {o["value"] for o in legacy_field["options"]} == {"Alpha", "Beta", "Gamma"}

            # The migrated category value still works going forward too.
            create_resp = client.post(
                "/tasks", json={"title": "New task", "category": "meeting"}, headers=headers
            )
            assert create_resp.status_code == 201
    finally:
        app.dependency_overrides.clear()
