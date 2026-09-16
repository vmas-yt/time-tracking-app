from datetime import datetime

from sqlalchemy.orm import Session

from app.models import TimeEntry, TimerStatus


def open_entry_for_task(db: Session, task_id: str) -> TimeEntry | None:
    return (
        db.query(TimeEntry)
        .filter(TimeEntry.task_id == task_id, TimeEntry.status != TimerStatus.STOPPED)
        .first()
    )


def running_entry_for_user(db: Session, user_id: str) -> TimeEntry | None:
    return (
        db.query(TimeEntry)
        .filter(TimeEntry.user_id == user_id, TimeEntry.status == TimerStatus.RUNNING)
        .first()
    )


def open_entries_for_user(db: Session, user_id: str) -> list[TimeEntry]:
    return (
        db.query(TimeEntry)
        .filter(TimeEntry.user_id == user_id, TimeEntry.status != TimerStatus.STOPPED)
        .all()
    )


def pause_entry(entry: TimeEntry, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    if entry.last_resumed_at:
        entry.accumulated_seconds += (now - entry.last_resumed_at).total_seconds()
    entry.last_resumed_at = None
    entry.status = TimerStatus.PAUSED


def resume_entry(entry: TimeEntry, now: datetime | None = None) -> None:
    entry.last_resumed_at = now or datetime.utcnow()
    entry.status = TimerStatus.RUNNING


def stop_entry(entry: TimeEntry, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    if entry.status == TimerStatus.RUNNING and entry.last_resumed_at:
        entry.accumulated_seconds += (now - entry.last_resumed_at).total_seconds()
    entry.last_resumed_at = None
    entry.status = TimerStatus.STOPPED
    entry.ended_at = now


def elapsed_seconds(entry: TimeEntry, now: datetime | None = None) -> float:
    elapsed = entry.accumulated_seconds
    if entry.status == TimerStatus.RUNNING and entry.last_resumed_at:
        now = now or datetime.utcnow()
        elapsed += (now - entry.last_resumed_at).total_seconds()
    return elapsed
