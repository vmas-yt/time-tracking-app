"""RBAC Round B3 (custom roles + granular permissions) schema verification,
same rigor as `test_migration_old_schema_with_real_data.py` /
`test_migration_manual_time_entry_with_real_data.py`, extended for this
round's own (much smaller) schema change: one brand-new table,
`role_permission_audit_entries` (`app.models.RolePermissionAuditEntry`).

Unlike those two files, this round adds no new *column* on an existing table
and no native-enum change -- there is deliberately no new
`_migrate_...` function in `app/services/migrations.py` for it (see that
module's own docstring, item 9, and `docs/design/custom-roles-design.md`
§6.5 for the db-admin sign-off reasoning). This test exists specifically to
prove that "no migration code needed" conclusion empirically rather than
merely asserting it in prose:

  1. Simulates an already-deployed Postgres database at the shape it has
     *today* (`roles`, `role_permissions`, `users` already exist and are
     already populated with real rows -- builtins plus one custom role and
     one user holding it) but strictly *before* this round: no
     `role_permission_audit_entries` table at all.
  2. Runs this app's exact startup sequence (`Base.metadata.create_all` ->
     `ensure_schema_migrations`, the same order `app/main.py`'s lifespan
     uses) and confirms the new table now exists, with the expected columns,
     FKs, and index -- created by `create_all` alone, with
     `ensure_schema_migrations` remaining a no-op for it.
  3. Inserts real `RolePermissionAuditEntry` rows referencing the
     pre-existing real `Role`/`User` rows (both ORM inserts and a raw SQL
     insert, to also exercise the FKs at the DB level, not just via the
     ORM), and reads them back correctly, including via the
     `role_id, occurred_at` composite index's query shape
     (`WHERE role_id = :id ORDER BY occurred_at DESC`).
  4. Runs the whole sequence a second time to prove idempotency: no
     "table already exists" error from `create_all`, no error from
     `ensure_schema_migrations`, and the previously-inserted rows are
     untouched.
  5. Sanity-checks §6.3's occupancy-guard reasoning empirically: attempts a
     raw `DELETE FROM roles WHERE id = ...` for a role that an *inactive*
     user still references via `users.role_id`, and confirms Postgres
     actually raises an `IntegrityError` (not a silent no-op, not a clean
     success) -- exactly the failure mode solution-architect's reasoning in
     §6.3 says the occupancy guard must check inactive users, not just
     active ones, to avoid.

Targets a real local Postgres 16 instance specifically for (5) (SQLite never
enforces FK constraints in this project -- no `PRAGMA foreign_keys=ON` is set
anywhere in `app/database.py` -- so the exact failure mode under test can't
be reproduced there at all) and, as a secondary benefit, for (1)-(4) so the
whole scenario is verified against the real backend this table will actually
be deployed on. Skips itself if Postgres isn't reachable at
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
    ForeignKey,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.environ.get(
    "MIGRATION_TEST_POSTGRES_URL",
    "postgresql://app_user:app_password@localhost:5432/time_tracking",
)
SCHEMA = "migration_test_role_permission_audit"


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
    """Hand-build `roles`/`role_permissions`/`users` exactly as they exist
    today, right before this round: real tables, real rows -- but
    deliberately no `role_permission_audit_entries` table at all. Uses
    SQLAlchemy Core (a separate MetaData, not app.database.Base) so this is
    independent of whatever the current app models look like."""
    from app.models import UserRole

    metadata = MetaData()

    roles = Table(
        "roles",
        metadata,
        Column("id", String, primary_key=True),
        Column("key", String, nullable=False, unique=True),
        Column("name", String, nullable=False),
        Column("is_builtin", Boolean, nullable=False),
        Column("created_at", DateTime),
    )

    role_permissions = Table(
        "role_permissions",
        metadata,
        Column("id", String, primary_key=True),
        Column("role_id", ForeignKey("roles.id"), nullable=False),
        Column("permission_key", String, nullable=False),
        Column("created_at", DateTime),
    )

    users = Table(
        "users",
        metadata,
        Column("id", String, primary_key=True),
        Column("email", String, nullable=False, unique=True),
        Column("full_name", String, nullable=False),
        Column("hashed_password", String, nullable=False),
        Column("role", Enum(UserRole), nullable=True),
        Column("role_id", ForeignKey("roles.id"), nullable=True),
        Column("created_at", DateTime),
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
        Column("deactivated_at", DateTime, nullable=True),
        # deliberately no role_permission_audit_entries table anywhere below.
    )

    metadata.create_all(bind=engine)
    return roles, role_permissions, users


def test_new_table_created_by_create_all_and_works_against_real_data(old_schema_engine):
    from app.core.security import hash_password

    engine = old_schema_engine
    roles, role_permissions, users = _build_pre_round_schema(engine)

    admin_role_id = str(uuid.uuid4())
    custom_role_id = str(uuid.uuid4())
    actor_id = str(uuid.uuid4())
    holder_id = str(uuid.uuid4())  # will become inactive, still holding custom_role_id
    now = datetime.utcnow()

    with engine.begin() as conn:
        conn.execute(
            roles.insert(),
            [
                {
                    "id": admin_role_id,
                    "key": "admin",
                    "name": "Admin",
                    "is_builtin": True,
                    "created_at": now,
                },
                {
                    "id": custom_role_id,
                    "key": "team-lead",
                    "name": "Team Lead",
                    "is_builtin": False,
                    "created_at": now,
                },
            ],
        )
        conn.execute(
            role_permissions.insert(),
            {
                "id": str(uuid.uuid4()),
                "role_id": custom_role_id,
                "permission_key": "manage_teams",
                "created_at": now,
            },
        )
        conn.execute(
            users.insert(),
            [
                {
                    "id": actor_id,
                    "email": "admin@example.com",
                    "full_name": "Admin Actor",
                    "hashed_password": hash_password("password123"),
                    "role": "ADMIN",
                    "role_id": admin_role_id,
                    "created_at": now,
                    "is_active": True,
                    "deactivated_at": None,
                },
                {
                    "id": holder_id,
                    "email": "lead@example.com",
                    "full_name": "Former Lead",
                    "hashed_password": hash_password("password123"),
                    "role": None,
                    "role_id": custom_role_id,
                    "created_at": now,
                    "is_active": False,  # deactivated, but still references custom_role_id
                    "deactivated_at": now,
                },
            ],
        )

    # ---- Sanity: fixture really reproduces the pre-round shape -------------
    inspector = inspect(engine)
    assert "role_permission_audit_entries" not in set(inspector.get_table_names())

    # ---- Exactly app/main.py's lifespan sequence (schema portion) ---------
    from app.database import Base
    from app.services.migrations import ensure_schema_migrations

    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)  # must remain a no-op for this table

    # ---- 1. New table exists, with the expected shape ----------------------
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    assert "role_permission_audit_entries" in table_names

    columns = {c["name"]: c for c in inspector.get_columns("role_permission_audit_entries")}
    assert set(columns) == {
        "id",
        "role_id",
        "actor_id",
        "batch_id",
        "permission_key",
        "change_type",
        "occurred_at",
    }
    assert columns["role_id"]["nullable"] is False
    assert columns["actor_id"]["nullable"] is False
    assert columns["batch_id"]["nullable"] is False
    assert columns["permission_key"]["nullable"] is False
    assert columns["change_type"]["nullable"] is False

    fks = inspector.get_foreign_keys("role_permission_audit_entries")
    fk_targets = {(tuple(fk["constrained_columns"]), fk["referred_table"]) for fk in fks}
    assert (("role_id",), "roles") in fk_targets
    assert (("actor_id",), "users") in fk_targets

    index_names = {idx["name"] for idx in inspector.get_indexes("role_permission_audit_entries")}
    assert "ix_role_permission_audit_entries_role_id_occurred_at" in index_names
    role_id_occurred_at_index = next(
        idx
        for idx in inspector.get_indexes("role_permission_audit_entries")
        if idx["name"] == "ix_role_permission_audit_entries_role_id_occurred_at"
    )
    assert role_id_occurred_at_index["column_names"] == ["role_id", "occurred_at"]

    # ---- 2. Real inserts against real pre-existing Role/User rows ----------
    from app.models import RolePermissionAuditEntry

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    batch_1 = str(uuid.uuid4())
    t1 = datetime(2026, 9, 1, 9, 0, 0)
    t2 = datetime(2026, 9, 2, 9, 0, 0)
    try:
        db.add(
            RolePermissionAuditEntry(
                role_id=custom_role_id,
                actor_id=actor_id,
                batch_id=batch_1,
                permission_key="manage_teams",
                change_type="added",
                occurred_at=t1,
            )
        )
        db.add(
            RolePermissionAuditEntry(
                role_id=custom_role_id,
                actor_id=actor_id,
                batch_id=batch_1,
                permission_key="view_all_tasks",
                change_type="added",
                occurred_at=t1,
            )
        )
        db.commit()
    finally:
        db.close()

    # Also a raw-SQL insert, so the FKs are exercised at the DB level too,
    # not only through the ORM's own bookkeeping.
    batch_2 = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO role_permission_audit_entries
                    (id, role_id, actor_id, batch_id, permission_key, change_type, occurred_at)
                VALUES
                    (:id, :role_id, :actor_id, :batch_id, :permission_key, :change_type, :occurred_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "role_id": custom_role_id,
                "actor_id": actor_id,
                "batch_id": batch_2,
                "permission_key": "manage_teams",
                "change_type": "removed",
                "occurred_at": t2,
            },
        )

    # ---- 3. Read back, in the exact query shape GET /roles/{id}/audit uses -
    db = SessionLocal()
    try:
        rows = (
            db.query(RolePermissionAuditEntry)
            .filter(RolePermissionAuditEntry.role_id == custom_role_id)
            .order_by(RolePermissionAuditEntry.occurred_at.desc())
            .all()
        )
        assert [(r.batch_id, r.permission_key, r.change_type) for r in rows] == [
            (batch_2, "manage_teams", "removed"),
            (batch_1, "manage_teams", "added"),
            (batch_1, "view_all_tasks", "added"),
        ]
        assert all(r.role_id == custom_role_id for r in rows)
        assert all(r.actor_id == actor_id for r in rows)
    finally:
        db.close()

    # ---- 4. Idempotency: running the whole sequence again must not error --
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)

    db = SessionLocal()
    try:
        count = (
            db.query(RolePermissionAuditEntry)
            .filter(RolePermissionAuditEntry.role_id == custom_role_id)
            .count()
        )
        assert count == 3  # unchanged, nothing duplicated or lost
    finally:
        db.close()

    # ---- 5. §6.3 sanity check: hard-deleting a role an *inactive* user -----
    #         still references must fail loudly on Postgres, not silently
    #         succeed or corrupt data -- this is the exact risk
    #         solution-architect's design doc reasoning is based on.
    with engine.connect() as conn:
        inactive_holder = conn.execute(
            text("SELECT is_active, role_id FROM users WHERE id = :id"), {"id": holder_id}
        ).fetchone()
    assert inactive_holder == (False, custom_role_id)  # fixture sanity

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM roles WHERE id = :id"), {"id": custom_role_id})

    # And the role_permission_audit_entries FK on role_id is equally real:
    # deleting a role with audit history attempted directly (bypassing the
    # application-level 409 guard entirely) must also fail loudly on
    # Postgres, for the same reason.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": holder_id})
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM roles WHERE id = :id"), {"id": custom_role_id})
