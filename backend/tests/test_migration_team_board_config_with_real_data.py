"""Round C (team-scoped boards) schema verification, same rigor as
`test_migration_manual_time_entry_with_real_data.py` /
`test_migration_role_permission_audit_new_table.py`, extended for this
round's own migration
(`app/services/migrations.py::_migrate_team_board_config_backfill`).

Unlike `role_permission_audit_entries` (a brand-new table with zero existing
data to reconcile), this round's new table interacts with a table that
already has live, possibly admin-changed data on any deployed environment:
the `board_config` singleton (`id="default"`). This file proves, against
real inserted data on a real Postgres 16 instance:

  1. Simulates an already-deployed database (real `departments`/`teams` rows,
     including a *non-default* `board_config.swimlane_field` value, exactly
     the "an admin already changed the global setting away from ASSIGNEE"
     scenario the design doc's §7.2/§7.4 discuss) but strictly *before* this
     round: no `team_board_configs` table at all.
  2. Runs this app's exact startup sequence (`Base.metadata.create_all` ->
     `ensure_schema_migrations`) and confirms every currently-*active* team
     gets a `team_board_configs` row copying the *current*
     `board_config.swimlane_field` value, and a soft-deactivated team does
     NOT get one.
  3. Confirms the real bug caught in the design doc's original §7.2 sketch:
     that sketch's `else "assignee"` fallback (the enum member's lowercase
     `.value`, not the `.name` this project's own `Enum(...)` columns
     actually store) would have made the migration crash outright on
     Postgres for a fresh install where `board_config` has no row yet —
     reproduced directly here as a `DataError`, then shown *not* to occur
     with the shipped fallback (`SwimlaneField.ASSIGNEE.name`).
  4. Confirms idempotency (run the whole sequence twice: no error, no
     duplicate rows, no value drift) *and* the specific idempotency shape
     db-admin chose over the design doc's original "the whole table is
     empty" gate: a per-team, insert-if-missing check that (a) never
     overwrites an already-set row (an admin's own `PATCH`, simulated here
     directly against the ORM), and (b) still catches a team created *after*
     the first migration run, on the very next restart — proving the
     original one-shot gate would have permanently missed both a later-added
     team and any team that happened to get a stray row before the backfill
     ran, while this shape does not.
  5. Confirms the enum reuse across two tables is genuinely conflict-free at
     the Postgres catalog level: exactly one `swimlanefield` native enum type
     exists, shared by both `board_config.swimlane_field` and
     `team_board_configs.swimlane_field`.

A second test in this file (`test_fresh_sqlite_database_handles_team_board_config`)
covers the complementary "completely fresh database" case on SQLite — no
pre-existing `board_config` row, no pre-existing teams beyond the bootstrap
"General" team — confirming the fallback default path works end to end
there too and the ORM can read the seeded row back correctly.

Targets a real local Postgres 16 instance for (1)-(5) specifically for the
native-enum behavior, which can't be simulated on SQLite (no real native enum
type there at all — see app/services/migrations.py's module docstring).
Skips itself if Postgres isn't reachable at MIGRATION_TEST_POSTGRES_URL
(defaults to the local dev instance described in this project's
test-running docs).
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
from sqlalchemy.exc import DataError
from sqlalchemy.orm import sessionmaker

from app.models import SwimlaneField

POSTGRES_URL = os.environ.get(
    "MIGRATION_TEST_POSTGRES_URL",
    "postgresql://app_user:app_password@localhost:5432/time_tracking",
)
SCHEMA = "migration_test_team_board_config"


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
    """Hand-build `departments`/`teams`/`board_config` exactly as they exist
    today, right before this round: real tables, real rows -- but
    deliberately no `team_board_configs` table at all. Uses SQLAlchemy Core
    (a separate MetaData, not app.database.Base) so this is independent of
    whatever the current app models look like. `teams.manager_id` is left as
    a plain nullable String (no FK) here -- this round doesn't touch that
    relationship and no test below needs a real `users` row to exist."""
    metadata = MetaData()

    departments = Table(
        "departments",
        metadata,
        Column("id", String, primary_key=True),
        Column("name", String, nullable=False, unique=True),
        Column("is_active", Boolean, nullable=False),
        Column("created_at", DateTime),
    )

    teams = Table(
        "teams",
        metadata,
        Column("id", String, primary_key=True),
        Column("department_id", ForeignKey("departments.id"), nullable=False),
        Column("name", String, nullable=False),
        Column("manager_id", String, nullable=True),
        Column("is_active", Boolean, nullable=False),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
    )

    board_config = Table(
        "board_config",
        metadata,
        Column("id", String, primary_key=True),
        Column("swimlane_field", Enum(SwimlaneField), nullable=False),
        Column("updated_at", DateTime),
    )

    metadata.create_all(bind=engine)
    return departments, teams, board_config


def test_backfill_propagates_non_default_value_and_skips_inactive_team(old_schema_engine):
    engine = old_schema_engine
    departments, teams, board_config = _build_pre_round_schema(engine)

    dept_id = str(uuid.uuid4())
    engineering_id = str(uuid.uuid4())
    support_id = str(uuid.uuid4())
    legacy_inactive_id = str(uuid.uuid4())
    now = datetime.utcnow()

    with engine.begin() as conn:
        conn.execute(departments.insert(), {"id": dept_id, "name": "Ops", "is_active": True, "created_at": now})
        conn.execute(
            teams.insert(),
            [
                {
                    "id": engineering_id,
                    "department_id": dept_id,
                    "name": "Engineering",
                    "manager_id": None,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": support_id,
                    "department_id": dept_id,
                    "name": "Support",
                    "manager_id": None,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": legacy_inactive_id,
                    "department_id": dept_id,
                    "name": "Legacy (deactivated)",
                    "manager_id": None,
                    "is_active": False,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        # An admin already changed the global swim-lane setting away from the
        # ASSIGNEE default, on a real, already-deployed database.
        conn.execute(
            board_config.insert(),
            {"id": "default", "swimlane_field": SwimlaneField.CATEGORY, "updated_at": now},
        )

    # ---- Sanity: fixture reproduces the pre-round shape, raw values --------
    inspector = inspect(engine)
    assert "team_board_configs" not in set(inspector.get_table_names())
    with engine.connect() as conn:
        raw_global = conn.execute(
            text("SELECT swimlane_field FROM board_config WHERE id = 'default'")
        ).fetchone()
    assert raw_global == ("CATEGORY",)  # the member's .name, not .value -- fixture sanity

    # ---- Exactly app/main.py's lifespan sequence (schema portion) ---------
    from app.database import Base
    from app.services.migrations import ensure_schema_migrations

    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)  # the function under test

    # ---- 1. New table exists, seeded correctly for active teams only ------
    inspector = inspect(engine)
    assert "team_board_configs" in set(inspector.get_table_names())

    with engine.connect() as conn:
        rows = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                text("SELECT team_id, board_name, swimlane_field FROM team_board_configs")
            ).fetchall()
        }
    # NOTE: `Base.metadata.create_all` above also creates the *real* app's
    # full table set (users/tasks/etc, since this is the real app.database.Base,
    # not a scoped-down one) -- which in turn makes `_migrate_org_structure_backfill`
    # eligible to run too and seed its own bootstrap "General" department/team.
    # That's a realistic side effect of this fixture reusing the real Base
    # (an old, already-deployed DB has all these tables too), not a bug in
    # this test -- assertions below only ever check facts about *our* teams,
    # via membership, never exact-set-equality against the whole table.
    assert legacy_inactive_id not in rows  # the deactivated team gets no row
    assert engineering_id in rows and support_id in rows
    assert rows[engineering_id] == (None, "CATEGORY")  # copied the real global value, correct case
    assert rows[support_id] == (None, "CATEGORY")

    # ---- 2. The ORM reads these rows back correctly (proves the value is a
    #         genuinely valid enum label, not just "some string") ----------
    from app.models import TeamBoardConfig

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        cfg = db.get(TeamBoardConfig, engineering_id)
        assert cfg.swimlane_field == SwimlaneField.CATEGORY
        assert cfg.board_name is None
    finally:
        db.close()

    # ---- 3. Idempotency: running the whole sequence again must not error,
    #         must not duplicate/alter existing rows -------------------------
    with engine.connect() as conn:
        count_after_first_run = conn.execute(text("SELECT COUNT(*) FROM team_board_configs")).scalar()
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)
    with engine.connect() as conn:
        count_after_second_run = conn.execute(text("SELECT COUNT(*) FROM team_board_configs")).scalar()
    assert count_after_second_run == count_after_first_run  # unchanged -- no duplicates

    # ---- 4. Admin customization is never clobbered by a later run ---------
    db = SessionLocal()
    try:
        cfg = db.get(TeamBoardConfig, engineering_id)
        cfg.board_name = "Sprint Board"
        cfg.swimlane_field = SwimlaneField.PRIORITY
        db.commit()
    finally:
        db.close()

    # Also change the *global* default, to prove a later backfill run uses
    # whatever is current at that time for genuinely new rows, while never
    # touching Engineering's now admin-customized row.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE board_config SET swimlane_field = :v WHERE id = 'default'"),
            {"v": "PRIORITY"},
        )

    # ---- 5. A team created *after* the first backfill run still gets ------
    #         caught on the next restart (self-healing, unlike the design
    #         doc's original one-shot "table is empty" gate, which would
    #         have permanently skipped this team since the table was already
    #         non-empty from step 1). ----------------------------------------
    new_team_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            teams.insert(),
            {
                "id": new_team_id,
                "department_id": dept_id,
                "name": "New Team",
                "manager_id": None,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )

    ensure_schema_migrations(engine)

    db = SessionLocal()
    try:
        engineering_cfg = db.get(TeamBoardConfig, engineering_id)
        support_cfg = db.get(TeamBoardConfig, support_id)
        new_team_cfg = db.get(TeamBoardConfig, new_team_id)

        assert engineering_cfg.board_name == "Sprint Board"  # untouched by the re-run
        assert engineering_cfg.swimlane_field == SwimlaneField.PRIORITY  # untouched

        assert support_cfg.board_name is None  # never customized, still exactly as seeded
        assert support_cfg.swimlane_field == SwimlaneField.CATEGORY

        assert new_team_cfg is not None  # caught on this later run
        assert new_team_cfg.board_name is None
        assert new_team_cfg.swimlane_field == SwimlaneField.PRIORITY  # today's current global value

        assert db.get(TeamBoardConfig, legacy_inactive_id) is None  # still never touched
    finally:
        db.close()

    # ---- 6. Enum reuse is genuinely conflict-free: exactly one Postgres ----
    #         native enum type, shared by both columns. -----------------------
    with engine.connect() as conn:
        enum_types = conn.execute(
            text(
                "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
                "WHERE n.nspname = :schema AND t.typtype = 'e' AND t.typname LIKE '%swimlane%'"
            ),
            {"schema": SCHEMA},
        ).fetchall()
    assert [r[0] for r in enum_types] == ["swimlanefield"]  # exactly one, not a second type

    fk_targets = {
        (tuple(fk["constrained_columns"]), fk["referred_table"])
        for fk in inspector.get_foreign_keys("team_board_configs")
    }
    assert (("team_id",), "teams") in fk_targets


def test_naive_lowercase_fallback_would_have_crashed_on_postgres(old_schema_engine):
    """Directly reproduces the bug caught in the design doc's original §7.2
    sketch (`else "assignee"`, the enum member's lowercase `.value`) against
    real Postgres, then confirms the shipped fallback
    (`SwimlaneField.ASSIGNEE.name`, i.e. `"ASSIGNEE"`) does not have this
    problem. This is the exact class of near-miss this project's own history
    already has one instance of (see app/services/migrations.py's module
    docstring on `AuditAction`) -- proven here empirically, not assumed."""
    engine = old_schema_engine
    departments, teams, _board_config = _build_pre_round_schema(engine)

    dept_id = str(uuid.uuid4())
    team_a_id = str(uuid.uuid4())
    team_b_id = str(uuid.uuid4())
    now = datetime.utcnow()
    with engine.begin() as conn:
        conn.execute(departments.insert(), {"id": dept_id, "name": "Ops", "is_active": True, "created_at": now})
        conn.execute(
            teams.insert(),
            [
                {
                    "id": team_a_id,
                    "department_id": dept_id,
                    "name": "Team A",
                    "manager_id": None,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": team_b_id,
                    "department_id": dept_id,
                    "name": "Team B",
                    "manager_id": None,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )

    from app.database import Base
    from app.services.migrations import ensure_schema_migrations

    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)  # backfills team_a_id/team_b_id already -- delete them below to
    # isolate this test's own direct-INSERT scenario from the real migration's own (already-correct)
    # inserts, so this test exercises exactly the naive-vs-fixed literal in isolation.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM team_board_configs"))

    with pytest.raises(DataError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO team_board_configs (team_id, board_name, swimlane_field, updated_at) "
                    "VALUES (:team_id, NULL, :swimlane_field, :updated_at)"
                ),
                {"team_id": team_a_id, "swimlane_field": "assignee", "updated_at": datetime.utcnow()},
            )

    # The correctly-cased fallback the shipped migration actually uses works fine.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO team_board_configs (team_id, board_name, swimlane_field, updated_at) "
                "VALUES (:team_id, NULL, :swimlane_field, :updated_at)"
            ),
            {
                "team_id": team_b_id,
                "swimlane_field": SwimlaneField.ASSIGNEE.name,
                "updated_at": datetime.utcnow(),
            },
        )


def test_fallback_default_used_when_board_config_has_no_row_yet(old_schema_engine):
    """A fresh-ish deploy where nobody has ever opened the global
    board-config screen: `board_config` table exists (created by
    `Base.metadata.create_all`) but has zero rows. Confirms the migration
    does not crash and falls back to `SwimlaneField.ASSIGNEE`, the same
    hardcoded default `BoardConfig.swimlane_field`'s own column default
    already uses."""
    engine = old_schema_engine
    departments, teams, _board_config = _build_pre_round_schema(engine)

    dept_id = str(uuid.uuid4())
    team_id = str(uuid.uuid4())
    now = datetime.utcnow()
    with engine.begin() as conn:
        conn.execute(departments.insert(), {"id": dept_id, "name": "Ops", "is_active": True, "created_at": now})
        conn.execute(
            teams.insert(),
            {
                "id": team_id,
                "department_id": dept_id,
                "name": "Solo Team",
                "manager_id": None,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        # deliberately no INSERT into board_config -- it stays empty.

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM board_config")).scalar() == 0

    from app.database import Base
    from app.services.migrations import ensure_schema_migrations

    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)  # must not raise

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT swimlane_field FROM team_board_configs WHERE team_id = :id"), {"id": team_id}
        ).fetchone()
    assert row == ("ASSIGNEE",)


def test_fresh_sqlite_database_handles_team_board_config():
    """The complementary "completely fresh database" case: no pre-existing
    `board_config` row, no pre-existing teams beyond the org-structure
    bootstrap "General" team that `_migrate_org_structure_backfill` itself
    creates in the very same `ensure_schema_migrations` call. Runs on
    SQLite specifically to confirm the lazy/backfill story also works on the
    dialect with no real native enum type at the DB level at all."""
    from app.database import Base
    from app.models import SwimlaneField, TeamBoardConfig
    from app.services.migrations import ensure_schema_migrations

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)  # must not raise on a totally fresh database

    inspector = inspect(engine)
    assert "team_board_configs" in set(inspector.get_table_names())

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        configs = db.query(TeamBoardConfig).all()
        assert len(configs) == 1  # the bootstrap "General" team, and nothing else
        assert configs[0].swimlane_field == SwimlaneField.ASSIGNEE
        assert configs[0].board_name is None
    finally:
        db.close()

    # Idempotency, same as every other migration test in this project.
    Base.metadata.create_all(bind=engine)
    ensure_schema_migrations(engine)
    db = SessionLocal()
    try:
        assert db.query(TeamBoardConfig).count() == 1
    finally:
        db.close()
