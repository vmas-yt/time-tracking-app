"""RBAC Round B1 (additive-only schema) migration, verified against real
inserted data on real Postgres — same rigor as
`test_migration_old_schema_with_real_data.py` and
`test_migration_org_structure_with_real_data.py`, extended for this round's
own migration (`app/services/migrations.py::_migrate_rbac_schema_backfill`).

Simulates an already-deployed database at *today's* shape (i.e. already past
every prior round, including Round A's `departments`/`teams`/`team_id`) but
from *before* this round: no `roles`/`role_permissions` tables, no
`users.role_id` column. Confirms:

  1. Startup completes without error.
  2. Exactly 3 builtin `roles` rows are seeded (employee/manager/admin).
  3. Every pre-existing user's `role_id` is backfilled onto the *correct*
     builtin role — checked by joining back to `roles.key`, not just "some
     role_id is set" — matching against the raw pre-migration `role` column
     value this test asserts first (the upper-cased enum member *name*
     Postgres/SQLAlchemy actually stores, e.g. `'EMPLOYEE'`, not the
     lowercase `.value` — see app/services/migrations.py's module docstring
     for why a naive case assumption here would repeat this project's
     documented near-miss).
  4. Running the whole sequence a second time is a no-op: no duplicate role
     rows, no `role_id` changes for already-backfilled users.
  5. The regression case this round's design deliberately gets right in the
     *opposite* direction from Round A's `team_id`: a user created *after*
     the initial migration pass, via the still-unmodified legacy user
     creation path (no `role_id` set — simulating pre-B2, since B2 is the
     round that wires `role_id` into user creation), **does** get backfilled
     by a later startup. This is correct here specifically because, unlike
     `team_id = NULL` (a legitimate, permanent, admin-chosen state — see
     Round A's own regression test), `role_id = NULL` never carries an
     intentional meaning in this round: nothing ever sets it deliberately,
     so any row that has it is purely a timing artifact that must not be
     allowed to reach Round B2's cutover unbackfilled.
  6. `assert_admin`/login/authorization behavior is completely unaffected —
     the whole point of this round is zero behavior change; the legacy
     `users.role` enum column is still what every authorization check reads.

Targets a real local Postgres 16 instance so the native `Enum(UserRole)`
storage/comparison behavior (and the deliberately fail-loud case-mismatch
behavior on a mismatched literal against that native enum type) is verified
against the real target dialect, not just SQLite. Skips itself if Postgres
isn't reachable at MIGRATION_TEST_POSTGRES_URL (defaults to the local dev
instance described in this project's test-running docs).
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
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.environ.get(
    "MIGRATION_TEST_POSTGRES_URL",
    "postgresql://app_user:app_password@localhost:5432/time_tracking",
)
SCHEMA = "migration_test_rbac_b1"


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


def _build_pre_b1_schema(engine):
    """Hand-build `departments`/`teams`/`users` exactly as they exist today,
    right before this round: every prior migration already applied
    (including Round A's org structure — `users.team_id`, real
    `departments`/`teams` tables) but no `roles`/`role_permissions` tables,
    and no `users.role_id` column. Uses SQLAlchemy Core (a separate
    MetaData, not app.database.Base) so this is independent of whatever the
    current app models look like."""
    from app.models import UserRole

    metadata = MetaData()

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
        Column("manager_id", String, nullable=True),  # FK to users.id, added post-hoc for real below
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
    )

    users = Table(
        "users",
        metadata,
        Column("id", String, primary_key=True),
        Column("email", String, nullable=False, unique=True),
        Column("full_name", String, nullable=False),
        Column("hashed_password", String, nullable=False),
        Column("role", Enum(UserRole), nullable=False),
        Column("manager_id", ForeignKey("users.id"), nullable=True),
        Column("team_id", ForeignKey("teams.id"), nullable=True),
        Column("created_at", DateTime),
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
        Column("deactivated_at", DateTime, nullable=True),
        # deliberately no role_id column — this round's addition.
    )

    metadata.create_all(bind=engine)
    return departments, teams, users


def test_migration_backfills_role_id_from_pre_b1_schema(old_schema_engine):
    from app.core.security import hash_password
    from app.models import UserRole

    engine = old_schema_engine
    departments, teams, users = _build_pre_b1_schema(engine)

    department_id = str(uuid.uuid4())
    team_id = str(uuid.uuid4())
    employee_id = str(uuid.uuid4())
    manager_id = str(uuid.uuid4())
    admin_id = str(uuid.uuid4())

    with engine.begin() as conn:
        conn.execute(
            departments.insert(),
            {"id": department_id, "name": "Engineering", "is_active": True, "created_at": datetime.utcnow()},
        )
        conn.execute(
            teams.insert(),
            {
                "id": team_id,
                "department_id": department_id,
                "name": "Backend",
                "manager_id": None,
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
        )
        conn.execute(
            users.insert(),
            [
                {
                    "id": employee_id,
                    "email": "legacy-employee@example.com",
                    "full_name": "Legacy Employee",
                    "hashed_password": hash_password("password123"),
                    "role": UserRole.EMPLOYEE,
                    "manager_id": None,
                    "team_id": team_id,
                    "created_at": datetime.utcnow(),
                    "is_active": True,
                    "deactivated_at": None,
                },
                {
                    "id": manager_id,
                    "email": "legacy-manager@example.com",
                    "full_name": "Legacy Manager",
                    "hashed_password": hash_password("password123"),
                    "role": UserRole.MANAGER,
                    "manager_id": None,
                    "team_id": team_id,
                    "created_at": datetime.utcnow(),
                    "is_active": True,
                    "deactivated_at": None,
                },
                {
                    "id": admin_id,
                    "email": "legacy-admin@example.com",
                    "full_name": "Legacy Admin",
                    "hashed_password": hash_password("password123"),
                    "role": UserRole.ADMIN,
                    "manager_id": None,
                    "team_id": None,
                    "created_at": datetime.utcnow(),
                    "is_active": True,
                    "deactivated_at": None,
                },
            ],
        )

    # Sanity check the fixture really does reproduce the pre-B1 shape, and
    # that the raw stored `role` values really are the upper-cased enum
    # *names* (not `.value`) — confirms the migration's own empirically
    # verified assumption, not just this test's.
    inspector = inspect(engine)
    assert "roles" not in inspector.get_table_names()
    assert "role_permissions" not in inspector.get_table_names()
    assert "role_id" not in {c["name"] for c in inspector.get_columns("users")}

    with engine.connect() as conn:
        raw_roles = dict(conn.execute(text("SELECT id, role FROM users")).fetchall())
    assert raw_roles[employee_id] == "EMPLOYEE"
    assert raw_roles[manager_id] == "MANAGER"
    assert raw_roles[admin_id] == "ADMIN"

    # ---- Exactly app/main.py's lifespan sequence (schema portion) ---------
    from app.database import Base
    from app.services.migrations import ensure_schema_migrations

    Base.metadata.create_all(bind=engine)  # creates roles/role_permissions; leaves users alone
    ensure_schema_migrations(engine)  # the function under test

    SessionLocal = sessionmaker(bind=engine)

    # ---- 1. Exactly 3 builtin roles seeded ---------------------------------
    from app.models import Role

    db = SessionLocal()
    try:
        roles_by_key = {r.key: r for r in db.query(Role).all()}
        assert set(roles_by_key) == {"employee", "manager", "admin"}
        assert all(r.is_builtin for r in roles_by_key.values())
        assert roles_by_key["employee"].name == "Employee"
        assert roles_by_key["manager"].name == "Manager"
        assert roles_by_key["admin"].name == "Admin"
    finally:
        db.close()

    # ---- 2. Every pre-existing user's role_id backfilled to the *correct* -
    #         builtin role, not just "some" role_id -- checked by joining
    #         back to roles.key.
    with engine.connect() as conn:
        joined = dict(
            conn.execute(
                text(
                    "SELECT u.id, r.key FROM users u "
                    "JOIN roles r ON u.role_id = r.id"
                )
            ).fetchall()
        )
    assert joined[employee_id] == "employee"
    assert joined[manager_id] == "manager"
    assert joined[admin_id] == "admin"

    # ---- 3. Authorization is completely unaffected -- the legacy `role` ---
    #         enum column is untouched and still what every check reads.
    with engine.connect() as conn:
        raw_roles_after = dict(conn.execute(text("SELECT id, role FROM users")).fetchall())
    assert raw_roles_after == raw_roles

    # ---- 4. Idempotency: running it again must not error or duplicate -----
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)

    db = SessionLocal()
    try:
        assert db.query(Role).count() == 3
    finally:
        db.close()

    with engine.connect() as conn:
        joined_again = dict(
            conn.execute(
                text("SELECT u.id, r.key FROM users u JOIN roles r ON u.role_id = r.id")
            ).fetchall()
        )
    assert joined_again == joined

    # ---- 5. The regression case: a user created *after* the initial pass, -
    #         via the still-unmodified legacy path (no role_id set), must
    #         get backfilled by a later startup -- the opposite of Round A's
    #         team_id behavior, and deliberately so (see module docstring).
    from app.models import User

    new_user_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(
            User(
                id=new_user_id,
                email="new-hire-legacy-path@example.com",
                full_name="New Hire Legacy Path",
                hashed_password=hash_password("password123"),
                role=UserRole.MANAGER,
                team_id=None,
                is_active=True,
                # role_id deliberately omitted -- simulates today's user
                # creation code path, unmodified by this round.
            )
        )
        db.commit()
    finally:
        db.close()

    with engine.connect() as conn:
        pre_heal = conn.execute(
            text("SELECT role_id FROM users WHERE id = :id"), {"id": new_user_id}
        ).scalar()
    assert pre_heal is None  # confirms the ORM insert really didn't set it

    # A later startup pass -- this is the one that must self-heal the
    # straggler rather than leaving it stuck at NULL forever.
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)

    with engine.connect() as conn:
        healed = dict(
            conn.execute(
                text("SELECT u.id, r.key FROM users u JOIN roles r ON u.role_id = r.id")
            ).fetchall()
        )
    assert healed[new_user_id] == "manager"
    # Everyone backfilled in the first pass is still correct and untouched.
    assert healed[employee_id] == "employee"
    assert healed[manager_id] == "manager"
    assert healed[admin_id] == "admin"

    # And a further run after that is a true no-op (nothing left to heal).
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)
    with engine.connect() as conn:
        healed_again = dict(
            conn.execute(
                text("SELECT u.id, r.key FROM users u JOIN roles r ON u.role_id = r.id")
            ).fetchall()
        )
    assert healed_again == healed
    db = SessionLocal()
    try:
        assert db.query(Role).count() == 3  # still no duplicate seeding
    finally:
        db.close()

    # ---- 6. The real app, booted against this now-migrated DB, still ------
    #         authorizes exactly as before (zero behavior change).
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
            admin_login = client.post(
                "/auth/login",
                data={"username": "legacy-admin@example.com", "password": "password123"},
            )
            assert admin_login.status_code == 200
            admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

            # Admin-only endpoint (assert_admin-gated) still works for the
            # admin -- assert_admin still reads the legacy `role` enum,
            # untouched by this round, not the new role_id/roles table.
            resp = client.post(
                "/admin/custom-fields",
                json={"name": "Post-migration field", "field_type": "text"},
                headers=admin_headers,
            )
            assert resp.status_code == 201

            employee_login = client.post(
                "/auth/login",
                data={"username": "legacy-employee@example.com", "password": "password123"},
            )
            assert employee_login.status_code == 200
            employee_headers = {"Authorization": f"Bearer {employee_login.json()['access_token']}"}

            # And a non-admin is still rejected exactly as before.
            resp = client.post(
                "/admin/custom-fields",
                json={"name": "Should be rejected", "field_type": "text"},
                headers=employee_headers,
            )
            assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
