import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import User, UserRole
from app.services.bootstrap import ensure_default_dropdown_options


@pytest.fixture()
def db_engine():
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
