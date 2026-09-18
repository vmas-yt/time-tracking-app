"""Manual/retroactive time-logging feature (schema only) migration, verified
against real inserted data on real Postgres — same rigor as
`test_migration_old_schema_with_real_data.py` /
`test_migration_rbac_schema_with_real_data.py`, extended for this round's own
migration (`app/services/migrations.py::_migrate_manual_time_entry_columns`
and `::_migrate_audit_action_add_manual_time_logged`).

Simulates an already-deployed database at *today's* shape (i.e. already past
every prior round) but from *before* this round: no `tasks.is_manual_entry`/
`tasks.started_at` columns, no `time_entries.is_manual` column, and a native
Postgres `auditaction` enum type that does not yet have the
`MANUAL_TIME_LOGGED` label. Confirms:

  1. Startup completes without error.
  2. The three new columns exist afterward, and every pre-existing task/time
     entry row lands on the exactly-correct default (`is_manual_entry=False`,
     `started_at=NULL`, `is_manual=False`) — not merely "some value".
  3. Running the whole sequence a second time is a no-op: no error, no
     column/data drift.
  4. A fresh row can actually set `is_manual_entry=True` / `started_at=<a
     date>` / `is_manual=True` post-migration.
  5. The genuinely migration-relevant enum step: the native Postgres
     `auditaction` type gets `MANUAL_TIME_LOGGED` added, and a
     `TaskAuditEntry` can actually be inserted with
     `action=AuditAction.MANUAL_TIME_LOGGED` afterward — this is exactly the
     kind of enum-related step this project's near-miss history says to
     verify empirically, not assume (see app/services/migrations.py's module
     docstring).

Targets a real local Postgres 16 instance specifically for the native enum
behavior in (5), which can't be simulated on SQLite (no real native enum type
there at all). Skips itself if Postgres isn't reachable at
MIGRATION_TEST_POSTGRES_URL (defaults to the local dev instance described in
this project's test-running docs).
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
SCHEMA = "migration_test_manual_time_entry"


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


def _build_pre_round_schema(engine):
    """Hand-build `users`/`tasks`/`time_entries`/`task_audit_entries` exactly
    as they exist today, right before this round: no
    `tasks.is_manual_entry`/`tasks.started_at`, no `time_entries.is_manual`,
    and — critically — a native Postgres `auditaction` enum type built from
    the *old* `AuditAction` member set (no `MANUAL_TIME_LOGGED` label yet),
    so the `ALTER TYPE ... ADD VALUE` step under test has something real to
    do. Uses SQLAlchemy Core (a separate MetaData, not app.database.Base) so
    this is independent of whatever the current app models look like."""
    import enum

    from app.models import TaskStatus, TaskType, TimerStatus, UserRole

    class OldAuditAction(str, enum.Enum):
        CREATED = "created"
        UPDATED = "updated"
        STATUS_CHANGED = "status_changed"
        COMMENTED = "commented"
        TIMER_STARTED = "timer_started"
        TIMER_PAUSED = "timer_paused"
        TIMER_RESUMED = "timer_resumed"
        TIMER_STOPPED = "timer_stopped"
        # deliberately no MANUAL_TIME_LOGGED -- this round's addition.

    metadata = MetaData()

    users = Table(
        "users",
        metadata,
        Column("id", String, primary_key=True),
        Column("email", String, nullable=False, unique=True),
        Column("full_name", String, nullable=False),
        Column("hashed_password", String, nullable=False),
        Column("role", Enum(UserRole), nullable=False),
        Column("created_at", DateTime),
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
    )

    tasks = Table(
        "tasks",
        metadata,
        Column("id", String, primary_key=True),
        Column("project_id", String, nullable=True),
        Column("assignee_id", ForeignKey("users.id"), nullable=True),
        Column("created_by_id", ForeignKey("users.id"), nullable=False),
        Column("team_id", String, nullable=True),
        Column("title", String, nullable=False),
        Column("description", Text, nullable=True),
        Column("task_type", Enum(TaskType), nullable=False),
        Column("category", String, nullable=False),
        Column("category_other_text", String, nullable=True),
        Column("priority", String, nullable=False),
        Column("status", Enum(TaskStatus), nullable=False),
        Column("position", Integer, nullable=True),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
        Column("completed_at", DateTime, nullable=True),
        Column("first_in_progress_at", DateTime, nullable=True),
        Column("archived_at", DateTime, nullable=True),
        # deliberately no is_manual_entry / started_at -- this round's addition.
    )

    time_entries = Table(
        "time_entries",
        metadata,
        Column("id", String, primary_key=True),
        Column("task_id", ForeignKey("tasks.id"), nullable=False),
        Column("user_id", ForeignKey("users.id"), nullable=False),
        Column("status", Enum(TimerStatus), nullable=False),
        Column("started_at", DateTime),
        Column("last_resumed_at", DateTime, nullable=True),
        Column("accumulated_seconds", Float, nullable=False, server_default=text("0")),
        Column("ended_at", DateTime, nullable=True),
        # deliberately no is_manual -- this round's addition.
    )

    task_audit_entries = Table(
        "task_audit_entries",
        metadata,
        Column("id", String, primary_key=True),
        Column("task_id", ForeignKey("tasks.id"), nullable=False),
        Column("actor_id", ForeignKey("users.id"), nullable=False),
        Column("action", Enum(OldAuditAction, name="auditaction"), nullable=False),
        Column("detail", String, nullable=False),
        Column("created_at", DateTime),
    )

    metadata.create_all(bind=engine)
    return users, tasks, time_entries, task_audit_entries


def test_migration_adds_manual_time_entry_columns_and_enum_value(old_schema_engine):
    from app.core.security import hash_password
    from app.models import TaskStatus, TaskType, TimerStatus, UserRole

    engine = old_schema_engine
    users, tasks, time_entries, task_audit_entries = _build_pre_round_schema(engine)

    user_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    time_entry_id = str(uuid.uuid4())
    audit_id = str(uuid.uuid4())

    with engine.begin() as conn:
        conn.execute(
            users.insert(),
            {
                "id": user_id,
                "email": "legacy-user@example.com",
                "full_name": "Legacy User",
                "hashed_password": hash_password("password123"),
                "role": UserRole.EMPLOYEE,
                "created_at": datetime.utcnow(),
                "is_active": True,
            },
        )
        conn.execute(
            tasks.insert(),
            {
                "id": task_id,
                "project_id": None,
                "assignee_id": user_id,
                "created_by_id": user_id,
                "team_id": None,
                "title": "Legacy live-tracked task",
                "description": None,
                "task_type": TaskType.NORMAL,
                "category": "meeting",
                "category_other_text": None,
                "priority": "normal",
                "status": TaskStatus.COMPLETED,
                "position": 0,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "completed_at": datetime.utcnow(),
                "first_in_progress_at": datetime.utcnow(),
                "archived_at": None,
            },
        )
        conn.execute(
            time_entries.insert(),
            {
                "id": time_entry_id,
                "task_id": task_id,
                "user_id": user_id,
                "status": TimerStatus.STOPPED,
                "started_at": datetime.utcnow(),
                "last_resumed_at": None,
                "accumulated_seconds": 3600.0,
                "ended_at": datetime.utcnow(),
            },
        )
        conn.execute(
            task_audit_entries.insert(),
            {
                "id": audit_id,
                "task_id": task_id,
                "actor_id": user_id,
                "action": "TIMER_STOPPED",
                "detail": "Timer stopped",
                "created_at": datetime.utcnow(),
            },
        )

    # ---- Sanity: fixture really reproduces the pre-round shape -------------
    inspector = inspect(engine)
    assert "is_manual_entry" not in {c["name"] for c in inspector.get_columns("tasks")}
    assert "started_at" not in {c["name"] for c in inspector.get_columns("tasks")}
    assert "is_manual" not in {c["name"] for c in inspector.get_columns("time_entries")}

    with engine.connect() as conn:
        enum_labels_before = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "JOIN pg_namespace n ON n.oid = t.typnamespace "
                    "WHERE t.typname = 'auditaction' AND n.nspname = :schema"
                ),
                {"schema": SCHEMA},
            )
        }
    assert "MANUAL_TIME_LOGGED" not in enum_labels_before

    # ---- Exactly app/main.py's lifespan sequence (schema portion) ---------
    from app.database import Base
    from app.services.migrations import ensure_schema_migrations

    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)  # the function under test

    # ---- 1. New columns exist, correct defaults on the pre-existing rows --
    inspector = inspect(engine)
    task_columns = {c["name"] for c in inspector.get_columns("tasks")}
    time_entry_columns = {c["name"] for c in inspector.get_columns("time_entries")}
    assert "is_manual_entry" in task_columns
    assert "started_at" in task_columns
    assert "is_manual" in time_entry_columns

    with engine.connect() as conn:
        task_row = conn.execute(
            text("SELECT is_manual_entry, started_at FROM tasks WHERE id = :id"), {"id": task_id}
        ).fetchone()
        time_entry_row = conn.execute(
            text("SELECT is_manual FROM time_entries WHERE id = :id"), {"id": time_entry_id}
        ).fetchone()
    assert task_row == (False, None)
    assert time_entry_row == (False,)

    # ---- 2. Enum value added on the real native Postgres type -------------
    with engine.connect() as conn:
        enum_labels_after = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "JOIN pg_namespace n ON n.oid = t.typnamespace "
                    "WHERE t.typname = 'auditaction' AND n.nspname = :schema"
                ),
                {"schema": SCHEMA},
            )
        }
    assert "MANUAL_TIME_LOGGED" in enum_labels_after

    # ---- 3. Idempotency: running the whole sequence again must not error --
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)

    with engine.connect() as conn:
        task_row_again = conn.execute(
            text("SELECT is_manual_entry, started_at FROM tasks WHERE id = :id"), {"id": task_id}
        ).fetchone()
        time_entry_row_again = conn.execute(
            text("SELECT is_manual FROM time_entries WHERE id = :id"), {"id": time_entry_id}
        ).fetchone()
        enum_labels_second_pass = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "JOIN pg_namespace n ON n.oid = t.typnamespace "
                    "WHERE t.typname = 'auditaction' AND n.nspname = :schema"
                ),
                {"schema": SCHEMA},
            )
        }
    assert task_row_again == task_row
    assert time_entry_row_again == time_entry_row
    assert enum_labels_second_pass == enum_labels_after  # no duplicate label, no error

    # ---- 4. A fresh row can actually set the new fields post-migration ----
    from app.models import AuditAction, Task, TaskAuditEntry, TimeEntry

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    manual_task_id = str(uuid.uuid4())
    manual_started_at = datetime(2026, 9, 1, 9, 0, 0)
    try:
        db.add(
            Task(
                id=manual_task_id,
                assignee_id=user_id,
                created_by_id=user_id,
                title="Manually logged task",
                task_type=TaskType.NORMAL,
                category="meeting",
                priority="normal",
                status=TaskStatus.COMPLETED,
                is_manual_entry=True,
                started_at=manual_started_at,
                completed_at=datetime(2026, 9, 2, 17, 0, 0),
            )
        )
        db.add(
            TimeEntry(
                id=str(uuid.uuid4()),
                task_id=manual_task_id,
                user_id=user_id,
                status=TimerStatus.STOPPED,
                started_at=manual_started_at,
                accumulated_seconds=28800.0,
                ended_at=datetime(2026, 9, 2, 17, 0, 0),
                is_manual=True,
            )
        )
        db.add(
            TaskAuditEntry(
                id=str(uuid.uuid4()),
                task_id=manual_task_id,
                actor_id=user_id,
                action=AuditAction.MANUAL_TIME_LOGGED,
                detail="Manually logged 8h",
            )
        )
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        saved_task = db.get(Task, manual_task_id)
        assert saved_task.is_manual_entry is True
        assert saved_task.started_at == manual_started_at

        saved_entry = (
            db.query(TimeEntry).filter(TimeEntry.task_id == manual_task_id).one()
        )
        assert saved_entry.is_manual is True

        saved_audit = (
            db.query(TaskAuditEntry).filter(TaskAuditEntry.task_id == manual_task_id).one()
        )
        assert saved_audit.action == AuditAction.MANUAL_TIME_LOGGED
    finally:
        db.close()
