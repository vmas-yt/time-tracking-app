"""Cold-start admin seed (app/services/bootstrap.py) and the automatic
schema-migration patcher (app/services/migrations.py) — see
docs/design/auth-rbac-design.md §2.2/§3.4.
"""

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import app.services.bootstrap as bootstrap_module
from app.database import Base
from app.models import User, UserRole
from app.services.migrations import ensure_schema_migrations


class _FakeSettings:
    def __init__(self, email=None, password=None, name="Admin"):
        self.bootstrap_admin_email = email
        self.bootstrap_admin_password = password
        self.bootstrap_admin_name = name


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


# ---- ensure_bootstrap_admin -------------------------------------------------


def test_ensure_bootstrap_admin_seeds_when_table_empty(db_session, monkeypatch):
    monkeypatch.setattr(
        bootstrap_module,
        "get_settings",
        lambda: _FakeSettings(email="admin@example.com", password="password123"),
    )
    bootstrap_module.ensure_bootstrap_admin(db_session)

    users = db_session.query(User).all()
    assert len(users) == 1
    assert users[0].email == "admin@example.com"
    assert users[0].role == UserRole.ADMIN
    assert users[0].is_active is True


def test_ensure_bootstrap_admin_noop_without_env_vars(db_session, monkeypatch):
    """Table stays empty (and the app doesn't crash) if the operator hasn't
    configured the bootstrap env vars yet."""
    monkeypatch.setattr(bootstrap_module, "get_settings", lambda: _FakeSettings())
    bootstrap_module.ensure_bootstrap_admin(db_session)
    assert db_session.query(User).count() == 0


def test_ensure_bootstrap_admin_never_touches_a_non_empty_table(db_session, monkeypatch):
    """Not a 'reset'/'ensure an admin always exists' routine — must never
    fire once the table has any row in it, even if bootstrap env vars are
    (still) set."""
    existing = User(
        email="existing@example.com",
        full_name="Existing",
        hashed_password="x",
        role=UserRole.EMPLOYEE,
    )
    db_session.add(existing)
    db_session.commit()

    monkeypatch.setattr(
        bootstrap_module,
        "get_settings",
        lambda: _FakeSettings(email="admin@example.com", password="password123"),
    )
    bootstrap_module.ensure_bootstrap_admin(db_session)

    users = db_session.query(User).all()
    assert len(users) == 1
    assert users[0].email == "existing@example.com"


# ---- ensure_schema_migrations ------------------------------------------------


def _make_legacy_users_table(engine):
    """A `users` table shaped like it would be on an already-deployed
    database from before `is_active`/`deactivated_at` existed."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id VARCHAR PRIMARY KEY,
                    email VARCHAR NOT NULL,
                    full_name VARCHAR NOT NULL,
                    hashed_password VARCHAR NOT NULL,
                    role VARCHAR NOT NULL,
                    manager_id VARCHAR,
                    created_at DATETIME
                )
                """
            )
        )


def test_ensure_schema_migrations_adds_missing_columns():
    engine = create_engine("sqlite:///:memory:")
    _make_legacy_users_table(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "is_active" not in columns
    assert "deactivated_at" not in columns

    ensure_schema_migrations(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "is_active" in columns
    assert "deactivated_at" in columns


def test_ensure_schema_migrations_is_idempotent():
    """Running it twice against the same engine must not error (no
    duplicate-column issue) — it must check column existence first rather
    than relying on `ADD COLUMN IF NOT EXISTS`."""
    engine = create_engine("sqlite:///:memory:")
    _make_legacy_users_table(engine)

    ensure_schema_migrations(engine)
    ensure_schema_migrations(engine)  # must not raise

    columns = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "is_active" in columns
    assert "deactivated_at" in columns


def test_ensure_schema_migrations_noop_when_users_table_absent():
    """A brand-new database with no tables yet — create_all handles this,
    the migration function must not error just because `users` isn't there
    yet."""
    engine = create_engine("sqlite:///:memory:")
    ensure_schema_migrations(engine)  # must not raise
