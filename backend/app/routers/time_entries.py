from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import AuditAction, Permission, Task, TaskStatus, TimeEntry, TimerStatus, User
from app.schemas import TimeEntryRead
from app.services.authz import assert_can_control_time_entry, has_permission
from app.services.tasks import record_audit, record_status_event
from app.services.timer import (
    elapsed_seconds,
    open_entries_for_user,
    open_entry_for_task,
    pause_entry,
    resume_entry,
    running_entry_for_user,
    stop_entry,
)

router = APIRouter(prefix="/time-entries", tags=["time-entries"])


def _serialize(entry: TimeEntry) -> TimeEntryRead:
    data = TimeEntryRead.model_validate(entry)
    data.elapsed_seconds = elapsed_seconds(entry)
    return data


def _get_owned_entry(db: Session, entry_id: str, current_user: User) -> TimeEntry:
    """Non-admins may only reach their own entries (404, not 403, to avoid
    revealing existence). Admins, and any custom role holding
    `view_all_time_entries`, may fetch any entry by id — the operational
    override for pause/resume/stop (RBAC Round B3, design doc §1.4.3);
    `start` doesn't call this at all, see `start_timer`, since it's
    tightened to assignee-only. `has_permission()` already returns True
    unconditionally for a floor admin, so the old explicit
    `role_key(...) == "admin"` branch collapses into this single check with
    no loss of coverage."""
    entry = db.get(TimeEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Time entry not found")
    if entry.user_id == current_user.id:
        return entry
    if has_permission(current_user, Permission.VIEW_ALL_TIME_ENTRIES):
        return entry
    raise HTTPException(status_code=404, detail="Time entry not found")


@router.get("", response_model=list[TimeEntryRead])
def list_time_entries(
    task_id: str | None = None,
    user_id: str | None = None,
    manager_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """No params: caller's own entries (unchanged). `user_id`: that user's
    entries, allowed for the user themself, their direct manager, or an
    admin. `manager_id`: every entry belonging to that manager's direct
    reports, allowed for that manager or an admin. Mutually exclusive."""
    if user_id and manager_id:
        raise HTTPException(status_code=400, detail="user_id and manager_id are mutually exclusive")

    if user_id:
        target = db.get(User, user_id)
        is_self = user_id == current_user.id
        is_their_manager = target is not None and target.manager_id == current_user.id
        if not (is_self or is_their_manager or has_permission(current_user, Permission.VIEW_ALL_TIME_ENTRIES)):
            raise HTTPException(status_code=403, detail="Not authorized to view this user's time entries")
        query = db.query(TimeEntry).filter(TimeEntry.user_id == user_id)
    elif manager_id:
        if not (manager_id == current_user.id or has_permission(current_user, Permission.VIEW_ALL_TIME_ENTRIES)):
            raise HTTPException(status_code=403, detail="Not authorized to view this team's time entries")
        query = db.query(TimeEntry).join(User, TimeEntry.user_id == User.id).filter(
            User.manager_id == manager_id
        )
    else:
        query = db.query(TimeEntry).filter(TimeEntry.user_id == current_user.id)

    if task_id:
        query = query.filter(TimeEntry.task_id == task_id)
    return [_serialize(e) for e in query.order_by(TimeEntry.started_at.desc()).all()]


@router.get("/open", response_model=list[TimeEntryRead])
def list_open_entries(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """A user's non-stopped entries: at most one RUNNING, plus any number
    of PAUSED entries on tasks that are In Progress (paused) or On Hold."""
    return [_serialize(e) for e in open_entries_for_user(db, current_user.id)]


@router.post("/start", response_model=TimeEntryRead, status_code=201)
def start_timer(
    task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Tightened to assignee-only (design doc §9.1): a task's creator or an
    # admin may edit the task, but starting a timer always attributes the
    # new entry to current_user, so only the assignee — the person actually
    # about to do the work — may start it. This drops the creator/admin
    # bypass that assert_can_edit_task would otherwise grant, for this one
    # action only.
    if current_user.id != task.assignee_id:
        raise HTTPException(status_code=403, detail="Only the task's assignee may start its timer")
    if task.status not in (TaskStatus.TODO, TaskStatus.ON_HOLD):
        raise HTTPException(
            status_code=409, detail="Timer can only be started from 'To Do' or 'On Hold'"
        )
    if open_entry_for_task(db, task_id) is not None:
        raise HTTPException(
            status_code=409, detail="This task already has an open timer; use resume instead"
        )
    if running_entry_for_user(db, current_user.id) is not None:
        raise HTTPException(status_code=409, detail="You already have a timer running on another task")

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

    from_status = task.status
    task.status = TaskStatus.IN_PROGRESS
    if task.first_in_progress_at is None:
        task.first_in_progress_at = now
        task.started_at = now
    record_status_event(db, task, current_user, from_status, TaskStatus.IN_PROGRESS)
    record_audit(db, task, current_user, AuditAction.STATUS_CHANGED, f"{from_status.value} -> in_progress")
    record_audit(db, task, current_user, AuditAction.TIMER_STARTED, "Timer started")

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This task already has an open timer, or you already have a timer running elsewhere",
        )
    db.refresh(entry)
    return _serialize(entry)


@router.post("/{entry_id}/pause", response_model=TimeEntryRead)
def pause_timer(
    entry_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    entry = _get_owned_entry(db, entry_id, current_user)
    assert_can_control_time_entry(current_user, entry)
    if entry.status != TimerStatus.RUNNING:
        raise HTTPException(status_code=409, detail=f"Cannot pause a timer in '{entry.status.value}' state")
    pause_entry(entry)
    record_audit(db, entry.task, current_user, AuditAction.TIMER_PAUSED, "Timer paused")
    db.commit()
    db.refresh(entry)
    return _serialize(entry)


@router.post("/{entry_id}/resume", response_model=TimeEntryRead)
def resume_timer(
    entry_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    entry = _get_owned_entry(db, entry_id, current_user)
    assert_can_control_time_entry(current_user, entry)
    if entry.status != TimerStatus.PAUSED:
        raise HTTPException(status_code=409, detail=f"Cannot resume a timer in '{entry.status.value}' state")
    # Concurrency check is scoped to the entry's owner, not the caller — an
    # admin resuming someone else's timer shouldn't be blocked by (or block)
    # the admin's own running timer, if any.
    other_running = running_entry_for_user(db, entry.user_id)
    if other_running is not None and other_running.id != entry.id:
        raise HTTPException(status_code=409, detail="You already have a timer running on another task")

    task = entry.task
    if task.status == TaskStatus.ON_HOLD:
        from_status = task.status
        task.status = TaskStatus.IN_PROGRESS
        record_status_event(db, task, current_user, from_status, TaskStatus.IN_PROGRESS)
        record_audit(db, task, current_user, AuditAction.STATUS_CHANGED, "on_hold -> in_progress")
    elif task.status != TaskStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=409, detail=f"Cannot resume a timer while the task is '{task.status.value}'"
        )

    resume_entry(entry)
    record_audit(db, task, current_user, AuditAction.TIMER_RESUMED, "Timer resumed")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a timer running on another task")
    db.refresh(entry)
    return _serialize(entry)


@router.post("/{entry_id}/stop", response_model=TimeEntryRead)
def stop_timer(
    entry_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    entry = _get_owned_entry(db, entry_id, current_user)
    assert_can_control_time_entry(current_user, entry)
    if entry.status == TimerStatus.STOPPED:
        raise HTTPException(status_code=409, detail="Timer is already stopped")

    stop_entry(entry)

    task = entry.task
    from_status = task.status
    now = datetime.utcnow()
    task.status = TaskStatus.COMPLETED
    task.completed_at = now
    record_status_event(db, task, current_user, from_status, TaskStatus.COMPLETED)
    record_audit(db, task, current_user, AuditAction.STATUS_CHANGED, f"{from_status.value} -> completed")
    record_audit(db, task, current_user, AuditAction.TIMER_STOPPED, "Timer stopped; task completed")

    db.commit()
    db.refresh(entry)
    return _serialize(entry)
