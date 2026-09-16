import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client):
    """Registers the first user of the (fresh, in-memory) database, which
    bootstraps to the admin role."""
    client.post(
        "/auth/register",
        json={"email": "dev@example.com", "full_name": "Dev User", "password": "password123"},
    )
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
