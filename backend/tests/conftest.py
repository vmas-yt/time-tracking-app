"""Test fixtures.

Two backends are supported, selected purely by the `DATABASE_URL` env var
that's already set (or not) before pytest starts:

  * unset / `sqlite:...` (the default): every test gets a brand-new
    `sqlite:///:memory:` engine (see `db_engine` below) — fast, fully
    isolated per test function, zero setup. This path is untouched from
    before this file was extended to also support Postgres.

  * a `postgresql://...` URL: the *whole test session* shares one Postgres
    engine — the app's own real `app.database.engine`, not a second one —
    scoped into a dedicated `pytest_suite` schema via `DB_SCHEMA` (see
    `app/database.py`), so the automated suite can never read/write
    anything sitting in `public` from a developer's own manual/interactive
    session against the same physical `time_tracking` database. This
    mirrors the technique `tests/test_migration_old_schema_with_real_data.py`
    already uses (`DROP SCHEMA IF EXISTS ... CASCADE` / `CREATE SCHEMA ...`
    + `search_path`) — same idea, applied to the whole suite instead of one
    file — under a distinct schema name (`pytest_suite` vs. that file's own
    `migration_test_old_schema`) so the two can never collide even when run
    in the same pytest session. Since Postgres isn't torn down/recreated
    between tests (too slow), per-test isolation instead comes from
    `TRUNCATE`ing every known table before each test (`_postgres_reset`
    below). Skips (not fails, not silently falls back to SQLite) if
    Postgres isn't reachable, exactly like that migration test does.

The env-var check and any resulting `DB_SCHEMA` assignment happen at the
very top of this file, before any `app.*` module is imported, because
`app.database.engine` is a module-level singleton built from
`get_settings()` (itself `@lru_cache`d) at import time — by the time
`app.database` is first imported anywhere (including transitively, e.g.
`from app.main import app` below), it's too late to change which schema it
points at.
"""

import os

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_USE_POSTGRES = bool(_DATABASE_URL) and not _DATABASE_URL.startswith("sqlite")
_PYTEST_SCHEMA = "pytest_suite"  # distinct from test_migration_...'s own migration_test_old_schema

if _USE_POSTGRES:
    os.environ["DB_SCHEMA"] = _PYTEST_SCHEMA

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import User, UserRole
from app.services.bootstrap import ensure_default_dropdown_options


def _maintenance_engine():
    """A plain engine with no `search_path` override — only ever used for
    the `DROP SCHEMA` / `CREATE SCHEMA` DDL itself, which schema-drop/create
    statements aren't relative to `search_path` anyway (mirrors
    test_migration_old_schema_with_real_data.py's own `_maintenance_engine`)."""
    return create_engine(_DATABASE_URL)


@pytest.fixture(scope="session")
def _postgres_schema():
    """Postgres-mode only: once per test session, rebuild the `pytest_suite`
    schema from scratch and create every current table in it via the app's
    own (by-now schema-scoped, see module docstring) `app.database.engine`.
    Returns whether Postgres mode is actually active, so dependent fixtures
    can no-op cheaply in the SQLite case. Skips the whole session (not a
    hard failure, not a silent SQLite fallback) if Postgres isn't reachable.
    """
    if not _USE_POSTGRES:
        yield False
        return

    try:
        maint = _maintenance_engine()
        with maint.connect() as conn:
            conn.execute(text("SELECT 1"))
        maint.dispose()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Postgres not reachable at {_DATABASE_URL}: {exc}")

    maint = _maintenance_engine()
    with maint.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_PYTEST_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {_PYTEST_SCHEMA}"))
    maint.dispose()

    from app.database import engine as app_engine

    Base.metadata.create_all(bind=app_engine)
    yield True


@pytest.fixture()
def _postgres_reset(_postgres_schema):
    """Postgres-mode only: TRUNCATE every table known to `Base.metadata`
    before each test, so tests stay isolated from each other despite
    sharing one physical schema/engine for the whole session. Table list is
    derived dynamically from `Base.metadata.tables` so it can't silently
    drift out of sync if a model is added later. `CASCADE` avoids needing to
    hand-sequence FK order.

    `db_engine` depends on this fixture (not just `_postgres_schema`) so
    that ordering is guaranteed regardless of pytest's own fixture-ordering
    heuristics: this must run *before* `client`/`auth_headers`/task fixtures
    do their own setup for the test, and they all go through `db_engine`.
    """
    if not _postgres_schema:
        return

    from app.database import engine as app_engine

    table_names = list(Base.metadata.tables.keys())
    quoted = ", ".join(f'"{name}"' for name in table_names)
    with app_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {quoted} CASCADE"))


@pytest.fixture()
def db_engine(_postgres_reset, _postgres_schema):
    if _postgres_schema:
        # The real app engine — already schema-scoped (module docstring),
        # already has every table (`_postgres_schema`), already truncated
        # for this test (`_postgres_reset`). Deliberately not a second,
        # separate engine: that would just be a redundant connection pool
        # pointed at the same schema, with no isolation benefit.
        from app.database import engine as app_engine

        return app_engine

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture()
def client(db_engine):
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # `main.py`'s lifespan seeds default task_category/task_priority
    # DropdownOption rows via `ensure_default_dropdown_options`, but (like
    # `ensure_bootstrap_admin`, see the `auth_headers` fixture below) it runs
    # against the real configured engine, not this in-memory test engine —
    # so tests need to seed it directly, the same way they seed the
    # bootstrap admin. Every task-creation test needs these rows present to
    # pass `services/tasks.py::validate_dropdown_value`.
    #
    # In Postgres mode `db_engine` *is* the real configured engine, so
    # lifespan's own call (via its separate `SessionLocal()`, same engine)
    # already seeds these rows first, during `TestClient(app)`'s startup
    # below, before this call runs — `ensure_default_dropdown_options` is
    # idempotent (checks for existing rows before inserting), so this call
    # is just a harmless no-op in that case.
    seed_db = TestingSessionLocal()
    try:
        ensure_default_dropdown_options(seed_db)
    finally:
        seed_db.close()

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client, db_engine):
    """`POST /auth/register` no longer exists — only an admin can create
    accounts (see docs/design/auth-rbac-design.md §4.1). Tests seed the
    bootstrap admin directly into the test DB (mirroring what
    `app/services/bootstrap.py::ensure_bootstrap_admin` does on a real
    cold-start deploy, which this in-memory test engine never runs through
    `main.py`'s lifespan against), then log in as that admin. Tests that
    need additional employee/manager accounts create them via `POST /users`
    using these headers.
    """
    TestingSessionLocal = sessionmaker(bind=db_engine)
    db = TestingSessionLocal()
    try:
        admin = User(
            email="dev@example.com",
            full_name="Dev User",
            hashed_password=hash_password("password123"),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
    finally:
        db.close()

    resp = client.post(
        "/auth/login", data={"username": "dev@example.com", "password": "password123"}
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_task(client, auth_headers, **overrides):
    payload = {"title": "Test Task", "category": "meeting"}
    payload.update(overrides)
    return client.post("/tasks", json=payload, headers=auth_headers).json()


@pytest.fixture()
def backlog_task_id(client, auth_headers):
    """A freshly created task, sitting in Backlog."""
    return _create_task(client, auth_headers)["id"]


@pytest.fixture()
def task_id(client, auth_headers, backlog_task_id):
    """A task moved to To Do — the usual starting point for timer tests."""
    client.patch(f"/tasks/{backlog_task_id}", json={"status": "todo"}, headers=auth_headers)
    return backlog_task_id
