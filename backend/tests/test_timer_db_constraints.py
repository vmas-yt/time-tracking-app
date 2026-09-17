"""DB-level backstop for the two timer invariants from docs/PRD.md
('only one open entry per task', 'only one RUNNING timer per user').

These bypass the application-level query-then-check guards in
app/services/timer.py entirely and write straight to the ORM, to prove the
partial unique indexes in app/models.py (TimeEntry.__table_args__) enforce
the invariant even if two requests raced past the app-level check.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Task, TimeEntry, TimerStatus, User


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _user_and_task(session, email="a@example.com", title="Task"):
    user = User(email=email, full_name="A", hashed_password="x")
    session.add(user)
    session.flush()
    task = Task(created_by_id=user.id, title=title, category="meeting")
    session.add(task)
    session.flush()
    return user, task


def test_db_rejects_second_open_entry_on_same_task(db_session):
    user, task = _user_and_task(db_session)
    db_session.add(TimeEntry(task_id=task.id, user_id=user.id, status=TimerStatus.RUNNING))
    db_session.commit()

    # Simulates a second request racing past the app-level open_entry_for_task
    # check and trying to insert a second open entry for the same task.
    db_session.add(TimeEntry(task_id=task.id, user_id=user.id, status=TimerStatus.PAUSED))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_db_allows_second_entry_once_first_is_stopped(db_session):
    user, task = _user_and_task(db_session)
    first = TimeEntry(task_id=task.id, user_id=user.id, status=TimerStatus.STOPPED)
    db_session.add(first)
    db_session.commit()

    # A stopped entry doesn't hold the "open" slot, so a fresh one is fine —
    # this isn't reachable via the real API (Stop is terminal for the task),
    # but confirms the partial index's WHERE clause is scoped correctly.
    db_session.add(TimeEntry(task_id=task.id, user_id=user.id, status=TimerStatus.RUNNING))
    db_session.commit()


def test_db_rejects_second_running_entry_for_same_user_across_tasks(db_session):
    user, task_a = _user_and_task(db_session, title="A")
    task_b = Task(created_by_id=user.id, title="B", category="meeting")
    db_session.add(task_b)
    db_session.flush()

    db_session.add(TimeEntry(task_id=task_a.id, user_id=user.id, status=TimerStatus.RUNNING))
    db_session.commit()

    # Simulates a second request racing past the app-level
    # running_entry_for_user check and starting/resuming a second RUNNING
    # entry for the same user on a different task.
    db_session.add(TimeEntry(task_id=task_b.id, user_id=user.id, status=TimerStatus.RUNNING))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_db_allows_running_entries_for_different_users(db_session):
    user_a, task_a = _user_and_task(db_session, email="a2@example.com", title="A")
    user_b = User(email="b2@example.com", full_name="B", hashed_password="x")
    db_session.add(user_b)
    db_session.flush()
    task_b = Task(created_by_id=user_b.id, title="B", category="meeting")
    db_session.add(task_b)
    db_session.flush()

    db_session.add(TimeEntry(task_id=task_a.id, user_id=user_a.id, status=TimerStatus.RUNNING))
    db_session.add(TimeEntry(task_id=task_b.id, user_id=user_b.id, status=TimerStatus.RUNNING))
    db_session.commit()  # no conflict — different users
