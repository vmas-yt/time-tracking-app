from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import AuditAction, Task, TaskAuditEntry, TaskStatus, TaskStatusEvent, TimerStatus, User
from app.services.timer import open_entry_for_task, pause_entry

# Manual status transitions available outside the timer. IN_PROGRESS and
# COMPLETED are reached only via /time-entries start|resume and stop.
ALLOWED_MANUAL_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.BACKLOG: {TaskStatus.TODO, TaskStatus.ON_HOLD},
    TaskStatus.TODO: {TaskStatus.BACKLOG, TaskStatus.ON_HOLD},
    TaskStatus.ON_HOLD: {TaskStatus.TODO, TaskStatus.BACKLOG},
    TaskStatus.IN_PROGRESS: {TaskStatus.ON_HOLD},
    TaskStatus.COMPLETED: set(),
}


def record_audit(db: Session, task: Task, actor: User, action: AuditAction, detail: str) -> None:
    db.add(TaskAuditEntry(task_id=task.id, actor_id=actor.id, action=action, detail=detail))


def record_status_event(db: Session, task: Task, actor: User, from_status: TaskStatus | None, to_status: TaskStatus) -> None:
    db.add(
        TaskStatusEvent(
            task_id=task.id,
            from_status=from_status,
            to_status=to_status,
            changed_by_id=actor.id,
        )
    )


def change_status(db: Session, task: Task, actor: User, new_status: TaskStatus) -> Task:
    """Apply a manual status change, per ALLOWED_MANUAL_TRANSITIONS.

    Moving IN_PROGRESS -> ON_HOLD auto-pauses the task's running timer.
    Moving ON_HOLD -> TODO/BACKLOG is blocked while an open timer entry
    exists (the employee must Resume or Stop it first).
    """
    if new_status not in ALLOWED_MANUAL_TRANSITIONS.get(task.status, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot move task from '{task.status.value}' to '{new_status.value}'",
        )

    if new_status == TaskStatus.ON_HOLD and task.status == TaskStatus.IN_PROGRESS:
        entry = open_entry_for_task(db, task.id)
        if entry and entry.status == TimerStatus.RUNNING:
            pause_entry(entry)
            record_audit(db, task, actor, AuditAction.TIMER_PAUSED, "Timer auto-paused (task moved to On Hold)")

    if new_status in (TaskStatus.TODO, TaskStatus.BACKLOG) and task.status == TaskStatus.ON_HOLD:
        if open_entry_for_task(db, task.id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Resume or stop this task's timer before moving it off On Hold",
            )

    from_status = task.status
    task.status = new_status
    record_status_event(db, task, actor, from_status, new_status)
    record_audit(db, task, actor, AuditAction.STATUS_CHANGED, f"{from_status.value} -> {new_status.value}")
    return task
