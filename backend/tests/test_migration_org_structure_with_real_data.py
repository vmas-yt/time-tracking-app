"""Round A (Department -> Team org structure) migration, verified against
real inserted data on real Postgres — same rigor as
`test_migration_old_schema_with_real_data.py`, extended for this round's own
migration (`app/services/migrations.py::_migrate_org_structure_backfill`).

Simulates an already-deployed database at *today's* shape (i.e. already past
every prior migration round: `users`/`tasks` have their current columns,
`category`/`priority` are already plain strings) but from *before* this
round: no `departments`/`teams` tables, no `users.team_id`/`tasks.team_id`
columns. Confirms:

  1. Startup completes without error (this in particular exercises the
     Team<->User circular FK dependency fix — `Team.manager_id` is declared
     `use_alter=True` specifically so `Base.metadata.create_all` doesn't
     raise `CircularDependencyError` creating the two new tables).
  2. A bootstrap "General" Department + Team is seeded exactly once.
  3. Every pre-existing user's/task's `team_id` is backfilled onto it.
  4. Running the whole sequence a second time is a no-op (idempotency): no
     duplicate "General" rows, pre-existing rows' `team_id` unchanged.
  5. The critical regression this migration's own design had to get right:
     a *null* `team_id` is a permanent, legitimate state (an unplaced new
     hire, or a user/task an admin has deliberately detached from a team) —
     not just a "hasn't been migrated yet" marker. A user/task created
     *after* the migration already ran, with an explicit team (or an
     explicit `None`), must never be dragged onto "General" by a later
     startup. If the backfill were keyed on `WHERE team_id IS NULL` instead
     of on whether the column existed before, every subsequent app restart
     would silently corrupt that intentional `None` back to "General" —
     exactly the class of bug this project's near-miss (see
     app/services/migrations.py's module docstring) was about: don't reason
     your way past a migration's behavior on real data, prove it.

Targets a real local Postgres 16 instance — the Team<->User circular FK
dependency behaves differently by dialect (a real deferred `ALTER TABLE ...
ADD CONSTRAINT` on Postgres; SQLAlchemy silently inlines the forward
reference into `CREATE TABLE` on SQLite instead, since SQLite has no `ALTER
TABLE ADD CONSTRAINT` at all) so this is exactly the kind of thing that must
be checked against the real target dialect, not just SQLite. Skips itself if
Postgres isn't reachable at MIGRATION_TEST_POSTGRES_URL (defaults to the
local dev instance described in this project's test-running docs).
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
SCHEMA = "migration_test_org_structure"


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


def _build_pre_round_a_schema(engine):
    """Hand-build `users`/`tasks` exactly as they exist today, right before
    this round: every prior migration already applied (native enums for
    role/task_type/status; plain-string category/priority; archived_at
    present) but no `team_id` column on either table, and no
    `departments`/`teams` tables at all. Uses SQLAlchemy Core (a separate
    MetaData, not app.database.Base) so this is independent of whatever the
    current app models look like."""
    from app.models import TaskStatus, TaskType, UserRole

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
        # deliberately no team_id column — this round's addition.
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
        Column("category", String, nullable=False),
        Column("category_other_text", String, nullable=True),
        Column("priority", String, nullable=False, server_default="normal"),
        Column("status", Enum(TaskStatus), nullable=False),
        Column("position", Integer, nullable=True),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
        Column("completed_at", DateTime, nullable=True),
        Column("first_in_progress_at", DateTime, nullable=True),
        Column("archived_at", DateTime, nullable=True),
        # deliberately no team_id column — this round's addition.
    )

    metadata.create_all(bind=engine)
    return users, tasks


def test_migration_backfills_org_structure_from_pre_round_a_schema(old_schema_engine):
    from app.core.security import hash_password
    from app.models import TaskStatus, TaskType, UserRole

    engine = old_schema_engine
    users, tasks = _build_pre_round_a_schema(engine)

    manager_id = str(uuid.uuid4())
    employee_id = str(uuid.uuid4())
    task_a_id = str(uuid.uuid4())
    task_b_id = str(uuid.uuid4())

    with engine.begin() as conn:
        conn.execute(
            users.insert(),
            [
                {
                    "id": manager_id,
                    "email": "legacy-manager@example.com",
                    "full_name": "Legacy Manager",
                    "hashed_password": hash_password("password123"),
                    "role": UserRole.MANAGER,
                    "manager_id": None,
                    "created_at": datetime.utcnow(),
                    "is_active": True,
                    "deactivated_at": None,
                },
                {
                    "id": employee_id,
                    "email": "legacy-employee@example.com",
                    "full_name": "Legacy Employee",
                    "hashed_password": hash_password("password123"),
                    "role": UserRole.EMPLOYEE,
                    "manager_id": manager_id,
                    "created_at": datetime.utcnow(),
                    "is_active": True,
                    "deactivated_at": None,
                },
            ],
        )
        conn.execute(
            tasks.insert(),
            [
                {
                    "id": task_a_id,
                    "project_id": None,
                    "assignee_id": employee_id,
                    "created_by_id": manager_id,
                    "title": "Legacy task A",
                    "description": "pre-existing row",
                    "task_type": TaskType.NORMAL,
                    "category": "meeting",
                    "category_other_text": None,
                    "priority": "normal",
                    "status": TaskStatus.BACKLOG,
                    "position": 0,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "completed_at": None,
                    "first_in_progress_at": None,
                    "archived_at": None,
                },
                {
                    "id": task_b_id,
                    "project_id": None,
                    "assignee_id": None,
                    "created_by_id": manager_id,
                    "title": "Legacy task B",
                    "description": None,
                    "task_type": TaskType.AD_HOC,
                    "category": "infrastructure",
                    "category_other_text": None,
                    "priority": "expedite",
                    "status": TaskStatus.TODO,
                    "position": 1,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "completed_at": None,
                    "first_in_progress_at": None,
                    "archived_at": None,
                },
            ],
        )

    # Sanity check the fixture really does reproduce the pre-Round-A shape.
    inspector = inspect(engine)
    assert "departments" not in inspector.get_table_names()
    assert "teams" not in inspector.get_table_names()
    assert "team_id" not in {c["name"] for c in inspector.get_columns("users")}
    assert "team_id" not in {c["name"] for c in inspector.get_columns("tasks")}

    # ---- Exactly app/main.py's lifespan sequence (schema portion) ---------
    from app.database import Base
    from app.services.migrations import ensure_schema_migrations

    Base.metadata.create_all(bind=engine)  # creates departments/teams; leaves users/tasks alone
    ensure_schema_migrations(engine)  # the function under test

    SessionLocal = sessionmaker(bind=engine)

    # ---- 1. Bootstrap "General" Department + Team seeded exactly once -----
    from app.models import Department, Team

    db = SessionLocal()
    try:
        departments = db.query(Department).all()
        assert len(departments) == 1
        assert departments[0].name == "General"
        assert departments[0].is_active is True

        teams = db.query(Team).all()
        assert len(teams) == 1
        general_team = teams[0]
        assert general_team.name == "General"
        assert general_team.department_id == departments[0].id
        assert general_team.manager_id is None
    finally:
        db.close()

    # ---- 2. Pre-existing users/tasks backfilled onto it --------------------
    with engine.connect() as conn:
        user_team_ids = dict(conn.execute(text("SELECT id, team_id FROM users")).fetchall())
        task_team_ids = dict(conn.execute(text("SELECT id, team_id FROM tasks")).fetchall())
    assert user_team_ids[manager_id] == general_team.id
    assert user_team_ids[employee_id] == general_team.id
    assert task_team_ids[task_a_id] == general_team.id
    assert task_team_ids[task_b_id] == general_team.id

    # ---- 3. Idempotency: running it again must not error or duplicate -----
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)

    db = SessionLocal()
    try:
        assert db.query(Department).count() == 1
        assert db.query(Team).count() == 1
    finally:
        db.close()

    with engine.connect() as conn:
        user_team_ids_again = dict(conn.execute(text("SELECT id, team_id FROM users")).fetchall())
        task_team_ids_again = dict(conn.execute(text("SELECT id, team_id FROM tasks")).fetchall())
    assert user_team_ids_again == user_team_ids
    assert task_team_ids_again == task_team_ids

    # ---- 4. The critical regression check: post-migration explicit team ---
    #         assignments (including an intentional `None`) must survive a
    #         later startup untouched — never dragged onto "General".
    from app.models import Task, User

    other_department_id = str(uuid.uuid4())
    other_team_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO departments (id, name, is_active, created_at) "
                "VALUES (:id, :name, true, :created_at)"
            ),
            {"id": other_department_id, "name": "Engineering", "created_at": datetime.utcnow()},
        )
        conn.execute(
            text(
                "INSERT INTO teams (id, department_id, name, manager_id, is_active, created_at, updated_at) "
                "VALUES (:id, :dept, :name, NULL, true, :c, :u)"
            ),
            {
                "id": other_team_id,
                "dept": other_department_id,
                "name": "Backend",
                "c": datetime.utcnow(),
                "u": datetime.utcnow(),
            },
        )

    new_user_with_team_id = str(uuid.uuid4())
    new_user_unplaced_id = str(uuid.uuid4())
    new_task_with_team_id = str(uuid.uuid4())
    new_task_unplaced_id = str(uuid.uuid4())

    db = SessionLocal()
    try:
        db.add(
            User(
                id=new_user_with_team_id,
                email="new-hire-placed@example.com",
                full_name="New Hire Placed",
                hashed_password=hash_password("password123"),
                role=UserRole.EMPLOYEE,
                team_id=other_team_id,
                is_active=True,
            )
        )
        db.add(
            User(
                id=new_user_unplaced_id,
                email="new-hire-unplaced@example.com",
                full_name="New Hire Unplaced",
                hashed_password=hash_password("password123"),
                role=UserRole.EMPLOYEE,
                team_id=None,  # explicitly not-yet-placed
                is_active=True,
            )
        )
        db.add(
            Task(
                id=new_task_with_team_id,
                created_by_id=manager_id,
                title="New task, explicitly on Backend",
                task_type=TaskType.NORMAL,
                category="meeting",
                priority="normal",
                status=TaskStatus.BACKLOG,
                team_id=other_team_id,
            )
        )
        db.add(
            Task(
                id=new_task_unplaced_id,
                created_by_id=manager_id,
                title="New task, explicitly unassigned",
                task_type=TaskType.NORMAL,
                category="meeting",
                priority="normal",
                status=TaskStatus.BACKLOG,
                team_id=None,
            )
        )
        db.commit()
    finally:
        db.close()

    # Also flip one of the *pre-existing*, already-backfilled users back to
    # an explicit None, exactly like an admin detaching them from a team.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET team_id = NULL WHERE id = :id"), {"id": employee_id}
        )

    # A third startup pass — this is the one that would silently corrupt
    # things if the backfill were keyed on `team_id IS NULL` instead of on
    # column presence.
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)

    with engine.connect() as conn:
        final_user_team_ids = dict(conn.execute(text("SELECT id, team_id FROM users")).fetchall())
        final_task_team_ids = dict(conn.execute(text("SELECT id, team_id FROM tasks")).fetchall())

    assert final_user_team_ids[new_user_with_team_id] == other_team_id  # untouched
    assert final_user_team_ids[new_user_unplaced_id] is None  # untouched, still unplaced
    assert final_user_team_ids[employee_id] is None  # detached user stays detached
    assert final_user_team_ids[manager_id] == general_team.id  # never touched, still General

    assert final_task_team_ids[new_task_with_team_id] == other_team_id  # untouched
    assert final_task_team_ids[new_task_unplaced_id] is None  # untouched
    assert final_task_team_ids[task_a_id] == general_team.id
    assert final_task_team_ids[task_b_id] == general_team.id

    # ---- 5. The real app, booted against this now-migrated DB, still works
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
                data={"username": "legacy-manager@example.com", "password": "password123"},
            )
            assert login.status_code == 200
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            resp = client.get("/tasks", headers=headers)
            assert resp.status_code == 200
            ids = {t["id"] for t in resp.json()}
            assert task_a_id in ids
    finally:
        app.dependency_overrides.clear()
