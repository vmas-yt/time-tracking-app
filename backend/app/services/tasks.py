from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import (
    AuditAction,
    CustomFieldDefinition,
    CustomFieldType,
    DropdownOption,
    DropdownOptionScope,
    ManualTimeEntrySettings,
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
from app.schemas import ManualEntryCreate
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


def record_status_event(
    db: Session,
    task: Task,
    actor: User,
    from_status: TaskStatus | None,
    to_status: TaskStatus,
    occurred_at: datetime | None = None,
) -> None:
    """`occurred_at` defaults to the column's own `datetime.utcnow` default
    (i.e. "now") when omitted. Manual/retroactive time logging is the one
    caller that passes it explicitly, backdating the completion event to the
    user's chosen Completion Date for cross-report consistency (Throughput,
    Cumulative Flow/Control Chart) — see services/tasks.py::create_manual_entry.
    """
    event = TaskStatusEvent(
        task_id=task.id,
        from_status=from_status,
        to_status=to_status,
        changed_by_id=actor.id,
    )
    if occurred_at is not None:
        event.occurred_at = occurred_at
    db.add(event)


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


def _resolve_max_days_back(db: Session) -> int:
    """Read-only settings lookup for manual-entry *validation* — deliberately
    never inserts the singleton row (that side effect belongs solely to
    `GET /admin/manual-entry-settings`, mirroring `BoardConfig`'s own lazy
    creation). Falls back to `ManualTimeEntrySettings.max_days_back`'s own
    model default (7) if the row hasn't been created yet."""
    settings = db.get(ManualTimeEntrySettings, "default")
    if settings is not None:
        return settings.max_days_back
    return 7


def validate_manual_entry_dates(db: Session, entry: ManualEntryCreate) -> None:
    """DB-dependent half of manual-entry validation. The future-date/
    ordering checks already ran in `ManualEntryCreate`'s own model_validator;
    this covers the two checks that need a DB read or aren't expressible
    without one: the admin-configurable N-day-back window (checked against
    Start Date only — Completion Date is independently already validated as
    `>= start_date` and `<= today`), and a coarse duration-impossibility
    guard. Shared by both manual-log endpoints (existing task, and on top of
    a brand-new task)."""
    max_days_back = _resolve_max_days_back(db)
    earliest_allowed = date.today() - timedelta(days=max_days_back)
    if entry.start_date < earliest_allowed:
        raise HTTPException(
            status_code=400,
            detail=f"start_date is more than {max_days_back} days in the past",
        )

    days_spanned = (entry.completion_date - entry.start_date).days + 1
    if entry.duration_minutes * 60 > days_spanned * 24 * 3600:
        raise HTTPException(
            status_code=400,
            detail="duration_minutes is not possible within the given date range",
        )


def create_manual_entry(db: Session, task: Task, actor: User, entry: ManualEntryCreate) -> TimeEntry:
    """The terminal manual/retroactive time-logging effect, shared by both
    manual-log endpoints (adding to an existing task, and on top of a
    brand-new task created in the same request). Caller is responsible for
    every precondition (existence, permission, archived, already-completed,
    existing-entries, date/duration validation — see
    routers/tasks.py's manual-log endpoints).

    Builds the synthetic `TimeEntry` already `STOPPED`, marks the task
    `is_manual_entry` + terminal `Completed` (exactly like Stop — no further
    timer/status transition is ever allowed out of it), and records exactly
    one backdated `TaskStatusEvent` plus two `TaskAuditEntry` rows (the
    existing STATUS_CHANGED pattern plus a new MANUAL_TIME_LOGGED one).

    Known, bounded limitation (not fixed here — flagging rather than
    silently leaving it unexplained): this event's `occurred_at` is
    backdated to Completion Date, which is only guaranteed to sort after
    every *other* event already recorded for this task if none of them
    happened, in real time, after that date. `routers/tasks.py::
    create_manual_log_task` backdates its own None->Backlog event to Start
    Date specifically to guarantee this for the brand-new-task path (where
    it would otherwise be wrong on *every* call, not just occasionally —
    see that function's docstring). For the existing-task path
    (`add_manual_log`), the target task's own prior status history is real
    and untouched by this function; if that task had a genuine status
    change (e.g. a manual move to On Hold and back) more recently than the
    chosen Completion Date — which the zero-existing-TimeEntry-rows
    precondition doesn't rule out, since manual status changes don't
    require a timer — `reports.py::cumulative_flow`'s ascending-
    `occurred_at` replay can show that task with a transient, incorrect
    status for the days between the backdated completion and the present.
    Closing this fully would mean either a new precondition (reject a
    completion date earlier than the task's last status change) or a
    change to `cumulative_flow`'s single-pass replay algorithm itself —
    both real design decisions for solution-architect, not something to
    improvise into a shared report function here.
    """
    start_dt = datetime.combine(entry.start_date, time.min)
    completion_dt = datetime.combine(entry.completion_date, time.min)

    time_entry = TimeEntry(
        task_id=task.id,
        user_id=actor.id,
        status=TimerStatus.STOPPED,
        is_manual=True,
        last_resumed_at=None,
        accumulated_seconds=float(entry.duration_minutes * 60),
        started_at=start_dt,
        ended_at=completion_dt,
    )
    db.add(time_entry)

    from_status = task.status
    task.is_manual_entry = True
    task.started_at = start_dt
    task.completed_at = completion_dt
    task.status = TaskStatus.COMPLETED
    record_status_event(db, task, actor, from_status, TaskStatus.COMPLETED, occurred_at=completion_dt)
    record_audit(db, task, actor, AuditAction.STATUS_CHANGED, f"{from_status.value} -> completed")

    hours, minutes = divmod(entry.duration_minutes, 60)
    record_audit(
        db,
        task,
        actor,
        AuditAction.MANUAL_TIME_LOGGED,
        f"Manually logged {hours}h {minutes}m (Start: {entry.start_date.isoformat()}, "
        f"Completion: {entry.completion_date.isoformat()})",
    )
    return time_entry


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
