from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Task, TimeEntry, TimerStatus, User
from app.schemas import TimeEntryRead

router = APIRouter(prefix="/time-entries", tags=["time-entries"])


def _serialize(entry: TimeEntry) -> TimeEntryRead:
    elapsed = entry.accumulated_seconds
    if entry.status == TimerStatus.RUNNING and entry.last_resumed_at:
        elapsed += (datetime.utcnow() - entry.last_resumed_at).total_seconds()
    data = TimeEntryRead.model_validate(entry)
    data.elapsed_seconds = elapsed
    return data


def _active_entry(db: Session, user_id: str) -> TimeEntry | None:
    """A user may have at most one non-stopped timer at a time, across all tasks."""
    return (
        db.query(TimeEntry)
        .filter(TimeEntry.user_id == user_id, TimeEntry.status != TimerStatus.STOPPED)
        .first()
    )


@router.get("", response_model=list[TimeEntryRead])
def list_time_entries(
    task_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(TimeEntry).filter(TimeEntry.user_id == current_user.id)
    if task_id:
        query = query.filter(TimeEntry.task_id == task_id)
    return [_serialize(e) for e in query.order_by(TimeEntry.started_at.desc()).all()]


@router.get("/active", response_model=TimeEntryRead | None)
def get_active_timer(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    entry = _active_entry(db, current_user.id)
    return _serialize(entry) if entry else None


@router.post("/start", response_model=TimeEntryRead, status_code=201)
def start_timer(
    task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if _active_entry(db, current_user.id):
        raise HTTPException(
            status_code=409, detail="A timer is already running or paused for this user"
        )
    now = datetime.utcnow()
    entry = TimeEntry(
        task_id=task_id,
        user_id=current_user.id,
        status=TimerStatus.RUNNING,
        started_at=now,
        last_resumed_at=now,
        accumulated_seconds=0.0,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _serialize(entry)


@router.post("/{entry_id}/pause", response_model=TimeEntryRead)
def pause_timer(
    entry_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    entry = _get_owned_entry(db, entry_id, current_user.id)
    if entry.status != TimerStatus.RUNNING:
        raise HTTPException(status_code=409, detail=f"Cannot pause a timer in '{entry.status.value}' state")
    now = datetime.utcnow()
    entry.accumulated_seconds += (now - entry.last_resumed_at).total_seconds()
    entry.last_resumed_at = None
    entry.status = TimerStatus.PAUSED
    db.commit()
    db.refresh(entry)
    return _serialize(entry)


@router.post("/{entry_id}/resume", response_model=TimeEntryRead)
def resume_timer(
    entry_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    entry = _get_owned_entry(db, entry_id, current_user.id)
    if entry.status != TimerStatus.PAUSED:
        raise HTTPException(status_code=409, detail=f"Cannot resume a timer in '{entry.status.value}' state")
    entry.last_resumed_at = datetime.utcnow()
    entry.status = TimerStatus.RUNNING
    db.commit()
    db.refresh(entry)
    return _serialize(entry)


@router.post("/{entry_id}/stop", response_model=TimeEntryRead)
def stop_timer(
    entry_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    entry = _get_owned_entry(db, entry_id, current_user.id)
    if entry.status == TimerStatus.STOPPED:
        raise HTTPException(status_code=409, detail="Timer is already stopped")
    now = datetime.utcnow()
    if entry.status == TimerStatus.RUNNING and entry.last_resumed_at:
        entry.accumulated_seconds += (now - entry.last_resumed_at).total_seconds()
    entry.last_resumed_at = None
    entry.status = TimerStatus.STOPPED
    entry.ended_at = now
    db.commit()
    db.refresh(entry)
    return _serialize(entry)


def _get_owned_entry(db: Session, entry_id: str, user_id: str) -> TimeEntry:
    entry = db.get(TimeEntry, entry_id)
    if not entry or entry.user_id != user_id:
        raise HTTPException(status_code=404, detail="Time entry not found")
    return entry
