from datetime import date, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import (
    AuditAction,
    CustomFieldDefinition,
    CustomFieldType,
    DropdownOption,
    DropdownOptionScope,
    Project,
    Task,
    TaskAuditEntry,
    TaskCustomValue,
    TaskStatus,
    TaskStatusEvent,
    TimeEntry,
    TimerStatus,
    User,
)
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


# ---- Custom fields, dropdown options, project linkage ----------------------
# See docs/design/custom-fields-admin-design.md §1.3, §2.8, §3.4.


def validate_dropdown_value(
    db: Session,
    scope: DropdownOptionScope,
    value: str,
    custom_field_id: str | None = None,
) -> None:
    """Category/priority validation (§2.8): `value` must resolve to a
    currently-active DropdownOption for the given scope."""
    exists = (
        db.query(DropdownOption)
        .filter(
            DropdownOption.scope == scope,
            DropdownOption.custom_field_id == custom_field_id,
            DropdownOption.value == value,
            DropdownOption.is_active.is_(True),
        )
        .first()
    )
    if not exists:
        raise HTTPException(status_code=400, detail=f"'{value}' is not a currently valid option")


def validate_custom_value(db: Session, field_def: CustomFieldDefinition, value: str) -> None:
    """Per-type value-shape validation for a TaskCustomValue (§1.3)."""
    field_type = field_def.field_type

    if field_type == CustomFieldType.TEXT:
        return

    if field_type == CustomFieldType.NUMBER:
        try:
            float(value)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail=f"field '{field_def.name}' expects a number"
            )
        return

    if field_type == CustomFieldType.DATE:
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail=f"field '{field_def.name}' expects a date in YYYY-MM-DD format",
            )
        return

    if field_type == CustomFieldType.BOOLEAN:
        if value not in ("true", "false"):
            raise HTTPException(
                status_code=400, detail=f"field '{field_def.name}' expects 'true' or 'false'"
            )
        return

    if field_type == CustomFieldType.SELECT:
        exists = (
            db.query(DropdownOption)
            .filter(
                DropdownOption.scope == DropdownOptionScope.CUSTOM_FIELD,
                DropdownOption.custom_field_id == field_def.id,
                DropdownOption.value == value,
                DropdownOption.is_active.is_(True),
            )
            .first()
        )
        if not exists:
            raise HTTPException(
                status_code=400,
                detail=f"'{value}' is not a valid option for field '{field_def.name}'",
            )
        return


def apply_custom_values(db: Session, task: Task, values: dict[str, str]) -> None:
    """Shared upsert-with-validation loop used by both `create_task` and
    `update_task` (§1.3) — one TaskCustomValue row per (task, field)."""
    for field_id, value in values.items():
        field_def = db.get(CustomFieldDefinition, field_id)
        if not field_def:
            raise HTTPException(status_code=400, detail=f"Unknown custom field '{field_id}'")
        validate_custom_value(db, field_def, value)
        existing = (
            db.query(TaskCustomValue)
            .filter(TaskCustomValue.task_id == task.id, TaskCustomValue.field_id == field_id)
            .first()
        )
        if existing:
            existing.value = value
        else:
            db.add(TaskCustomValue(task_id=task.id, field_id=field_id, value=value))


def validate_project_exists(db: Session, project_id: str | None) -> None:
    """§3.4: 400 if a non-null project_id doesn't resolve to a real Project."""
    if not project_id:
        return
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(
            status_code=400, detail="project_id does not reference an existing project"
        )


def total_logged_seconds(db: Session, task: Task) -> float:
    """§7.2: banked accumulated_seconds plus the live segment of any
    currently-RUNNING entry, summed across every TimeEntry the task has ever
    had (normally one for a completed task)."""
    total = 0.0
    for entry in db.query(TimeEntry).filter(TimeEntry.task_id == task.id).all():
        total += entry.accumulated_seconds
        if entry.status == TimerStatus.RUNNING and entry.last_resumed_at:
            total += (datetime.utcnow() - entry.last_resumed_at).total_seconds()
    return total
