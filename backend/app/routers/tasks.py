from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    AuditAction,
    DropdownOptionScope,
    Permission,
    Task,
    TaskAuditEntry,
    TaskComment,
    TaskCustomValue,
    TaskStatus,
    TimeEntry,
    User,
)
from app.schemas import (
    AuditEntryRead,
    CommentCreate,
    CommentRead,
    ManualEntryCreate,
    ManualTaskCreate,
    TaskBase,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)
from app.services.authz import assert_can_edit_task, assert_can_view_task, assert_has_permission, has_permission
from app.services.tasks import (
    apply_custom_values,
    change_status,
    create_manual_entry,
    record_audit,
    record_status_event,
    total_logged_seconds,
    validate_dropdown_value,
    validate_manual_entry_dates,
    validate_project_exists,
)
from app.services.teams import validate_team_id
from app.services.timer import open_entry_for_task
from app.services.users import validate_assignee_active

# TaskBase's own field names — used to strip the extra manual-entry fields
# (start_date/completion_date/duration_minutes) and custom_values off of
# ManualTaskCreate before constructing a Task(**kwargs), the same way
# TaskCreate's own custom_values is excluded below.
_TASK_BASE_FIELDS = set(TaskBase.model_fields.keys())

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _custom_values_map(db: Session, task_id: str) -> dict[str, str]:
    rows = db.query(TaskCustomValue).filter(TaskCustomValue.task_id == task_id).all()
    return {row.field_id: row.value for row in rows}


def _serialize(db: Session, task: Task) -> TaskRead:
    data = TaskRead.model_validate(task)
    data.custom_values = _custom_values_map(db, task.id)
    data.total_logged_seconds = total_logged_seconds(db, task)
    if task.status == TaskStatus.COMPLETED:
        data.card_date = task.completed_at
    elif task.started_at is not None:
        data.card_date = task.started_at
    else:
        data.card_date = task.created_at
    return data


def _get_task_or_404(db: Session, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _validate_task_fields(db: Session, task_in: TaskBase) -> None:
    """Shared field validation for creating a task — used by both the plain
    `POST /tasks` and the manual-log `POST /tasks/manual-log`, which share
    every `TaskBase` field unchanged."""
    validate_assignee_active(db, task_in.assignee_id)
    validate_project_exists(db, task_in.project_id)
    validate_dropdown_value(db, DropdownOptionScope.TASK_CATEGORY, task_in.category)
    validate_dropdown_value(db, DropdownOptionScope.TASK_PRIORITY, task_in.priority)
    if task_in.team_id is not None:
        validate_team_id(db, task_in.team_id)


def _build_task(db: Session, task_in: TaskBase, current_user: User) -> Task:
    """Shared task construction (defaulting assignee/team) for both
    `POST /tasks` and `POST /tasks/manual-log`. Caller adds the row, flushes,
    and records its own CREATED audit/status-event afterward."""
    task_data = task_in.model_dump(include=_TASK_BASE_FIELDS)
    task = Task(**task_data, created_by_id=current_user.id, status=TaskStatus.BACKLOG)
    if task.assignee_id is None:
        task.assignee_id = current_user.id
    if task.team_id is None:
        # One-time default at creation (never re-derived later, see the
        # comment on Task.team_id in models.py): the resolved assignee's
        # team_id — which, since assignee_id was just self-assigned to the
        # creator above when none was given, naturally covers both "an
        # assignee is given" (use their team) and "no assignee given" (use
        # the creator's team, because the creator *is* the assignee here).
        resolved_assignee = db.get(User, task.assignee_id) if task.assignee_id else None
        task.team_id = resolved_assignee.team_id if resolved_assignee else None
    return task


@router.get("", response_model=list[TaskRead])
def list_tasks(
    project_id: str | None = None,
    assignee_id: str | None = None,
    status_filter: TaskStatus | None = None,
    manager_id: str | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List tasks for the board.

    `manager_id` returns tasks assigned to anyone whose `manager_id` equals
    the given user — the "my team" board a line manager needs, without one
    round-trip per direct report. Non-admins are additionally restricted to
    tasks they can view (assignee, creator, or their assignee's manager),
    matching `services/authz.assert_can_view_task` used elsewhere.

    `include_archived` defaults to excluding archived tasks for everyone; a
    non-admin passing `true` is silently ignored (same pattern as
    `include_inactive` on `GET /users`) — only an admin can actually see
    archived tasks in the default list (§5.2).
    """
    query = db.query(Task)
    if project_id:
        query = query.filter(Task.project_id == project_id)
    if assignee_id:
        query = query.filter(Task.assignee_id == assignee_id)
    if status_filter:
        query = query.filter(Task.status == status_filter)
    if manager_id:
        query = query.filter(Task.assignee.has(User.manager_id == manager_id))
    if not (include_archived and has_permission(current_user, Permission.ARCHIVE_TASKS)):
        query = query.filter(Task.archived_at.is_(None))
    if not has_permission(current_user, Permission.VIEW_ALL_TASKS):
        query = query.filter(
            or_(
                Task.assignee_id == current_user.id,
                Task.created_by_id == current_user.id,
                Task.assignee.has(User.manager_id == current_user.id),
            )
        )
    tasks = query.order_by(Task.status, Task.position).all()
    return [_serialize(db, t) for t in tasks]


@router.post("", response_model=TaskRead, status_code=201)
def create_task(
    task_in: TaskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    _validate_task_fields(db, task_in)
    task = _build_task(db, task_in, current_user)
    db.add(task)
    db.flush()
    if task_in.custom_values:
        apply_custom_values(db, task, task_in.custom_values)
    record_audit(db, task, current_user, AuditAction.CREATED, f"Task created: {task.title}")
    record_status_event(db, task, current_user, None, TaskStatus.BACKLOG)
    db.commit()
    db.refresh(task)
    return _serialize(db, task)


@router.post("/manual-log", response_model=TaskRead, status_code=201)
def create_manual_log_task(
    task_in: ManualTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a brand-new task and manually log time against it in one shot
    (manual/retroactive time-logging feature). Same field validation as
    `POST /tasks` (assignee active, project exists, category/priority,
    team_id), plus the manual-entry date/duration validation, then the task
    is created exactly like `create_task` (Backlog, CREATED audit,
    None -> Backlog status event) before the manual log is applied on top
    (STATUS_CHANGED + MANUAL_TIME_LOGGED audit rows, Backlog -> Completed
    status event backdated to the completion date) — see
    services/tasks.py::create_manual_entry.

    The None -> Backlog event's `occurred_at` is backdated to Start Date
    (not left at the default "now") specifically for this path: the
    Backlog -> Completed event `create_manual_entry` records below is
    backdated to Completion Date, and Completion Date can be any day up to
    and including today. Leaving this creation event at real "now" would
    make it sort *after* that backdated completion event in
    `reports.py::cumulative_flow`'s ascending-`occurred_at` replay whenever
    Completion Date is today or in the past relative to the current
    instant — which is every single call, since Completion Date is
    validated to never be in the future. Cumulative Flow processes events
    in order and lets the last-processed one win, so without this fix the
    later-sorted (but logically earlier) creation event would permanently
    overwrite the task's replayed status back to Backlog, making every
    manually-logged new task look stuck in Backlog forever on the
    Cumulative Flow/Control Chart reports. Backdating to Start Date keeps
    this event's `occurred_at` <= the completion event's (`start_date <=
    completion_date` is already validated), so replay order matches actual
    logical order.
    """
    _validate_task_fields(db, task_in)
    validate_manual_entry_dates(db, task_in)

    task = _build_task(db, task_in, current_user)
    # Tightened to assignee-only (mirrors start_timer in time_entries.py):
    # `_build_task` defaults a missing assignee_id to current_user, but an
    # explicit assignee_id naming someone else is otherwise accepted by
    # `POST /tasks` -- a manual log always attributes the resulting
    # TimeEntry to current_user (see create_manual_entry), so creating one
    # for a task assigned to someone other than yourself would silently log
    # time under your identity for work nominally assigned to them.
    if task.assignee_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Manual time can only be logged for a task assigned to yourself",
        )
    db.add(task)
    db.flush()
    if task_in.custom_values:
        apply_custom_values(db, task, task_in.custom_values)
    record_audit(db, task, current_user, AuditAction.CREATED, f"Task created: {task.title}")
    record_status_event(
        db,
        task,
        current_user,
        None,
        TaskStatus.BACKLOG,
        occurred_at=datetime.combine(task_in.start_date, time.min),
    )

    create_manual_entry(db, task, current_user, task_in)

    db.commit()
    db.refresh(task)
    return _serialize(db, task)


@router.post("/{task_id}/manual-log", response_model=TaskRead, status_code=201)
def add_manual_log(
    task_id: str,
    entry_in: ManualEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a manual/retroactive time entry to an existing task. Terminal,
    exactly like Stop: the task becomes Completed and no further timer/manual
    status transition is ever allowed out of it. Manual and live tracking are
    mutually exclusive per task — enforced by requiring zero existing
    `TimeEntry` rows of any kind."""
    task = _get_task_or_404(db, task_id)
    # Tightened to assignee-only (mirrors start_timer in time_entries.py): a
    # task's creator or an admin may edit the task generally, but a manual
    # log always attributes the resulting TimeEntry to current_user (see
    # create_manual_entry), so only the assignee -- the person who actually
    # did the work -- may log it. This drops the creator/admin bypass that
    # assert_can_edit_task would otherwise grant, for this one action only.
    if current_user.id != task.assignee_id:
        raise HTTPException(status_code=403, detail="Only the task's assignee may log manual time for it")

    if task.archived_at is not None:
        raise HTTPException(status_code=409, detail="Cannot log time against an archived task")
    if task.status == TaskStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Task is already completed")

    existing_entry = db.query(TimeEntry).filter(TimeEntry.task_id == task_id).first()
    if existing_entry is not None:
        open_entry = open_entry_for_task(db, task_id)
        if task.status == TaskStatus.ON_HOLD and open_entry is not None:
            raise HTTPException(
                status_code=409,
                detail="This task has a paused timer — resume or stop it first",
            )
        raise HTTPException(status_code=409, detail="This task already has a time entry logged")

    validate_manual_entry_dates(db, entry_in)

    create_manual_entry(db, task, current_user, entry_in)
    db.commit()
    db.refresh(task)
    return _serialize(db, task)


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = _get_task_or_404(db, task_id)
    assert_can_view_task(current_user, task)
    return _serialize(db, task)


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: str,
    task_in: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _get_task_or_404(db, task_id)
    assert_can_edit_task(current_user, task)
    updates = task_in.model_dump(exclude_unset=True, exclude={"status", "custom_values"})

    if "assignee_id" in updates:
        validate_assignee_active(db, updates["assignee_id"])
    if "project_id" in updates:
        validate_project_exists(db, updates["project_id"])
    if "category" in updates:
        validate_dropdown_value(db, DropdownOptionScope.TASK_CATEGORY, updates["category"])
    if "priority" in updates:
        validate_dropdown_value(db, DropdownOptionScope.TASK_PRIORITY, updates["priority"])
    if "team_id" in updates:
        validate_team_id(db, updates["team_id"])

    if updates:
        for field, value in updates.items():
            setattr(task, field, value)
        record_audit(
            db, task, current_user, AuditAction.UPDATED, f"Updated fields: {', '.join(updates.keys())}"
        )

    if task_in.custom_values:
        apply_custom_values(db, task, task_in.custom_values)
        record_audit(
            db,
            task,
            current_user,
            AuditAction.UPDATED,
            f"Set custom fields: {', '.join(task_in.custom_values.keys())}",
        )

    if task_in.status is not None:
        change_status(db, task, current_user, task_in.status)

    db.commit()
    db.refresh(task)
    return _serialize(db, task)


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = _get_task_or_404(db, task_id)
    assert_can_edit_task(current_user, task)
    has_logged_time = db.query(TimeEntry).filter(TimeEntry.task_id == task_id).first() is not None
    if has_logged_time:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot delete a task with logged time entries — it would erase the "
                "audit trail and reporting history. Move it to a terminal status instead."
            ),
        )
    db.delete(task)
    db.commit()


@router.post("/{task_id}/archive", response_model=TaskRead)
def archive_task(
    task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Admin-only, orthogonal to `status` (§5.2). Idempotent — archiving an
    already-archived task just returns it unchanged, no error."""
    assert_has_permission(current_user, Permission.ARCHIVE_TASKS)
    task = _get_task_or_404(db, task_id)
    if task.archived_at is None:
        task.archived_at = datetime.utcnow()
        record_audit(db, task, current_user, AuditAction.UPDATED, "Task archived by admin")
        db.commit()
        db.refresh(task)
    return _serialize(db, task)


@router.post("/{task_id}/unarchive", response_model=TaskRead)
def unarchive_task(
    task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Symmetric to `archive_task` — admin-only, idempotent."""
    assert_has_permission(current_user, Permission.ARCHIVE_TASKS)
    task = _get_task_or_404(db, task_id)
    if task.archived_at is not None:
        task.archived_at = None
        record_audit(db, task, current_user, AuditAction.UPDATED, "Task unarchived by admin")
        db.commit()
        db.refresh(task)
    return _serialize(db, task)


@router.get("/{task_id}/comments", response_model=list[CommentRead])
def list_comments(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = _get_task_or_404(db, task_id)
    assert_can_view_task(current_user, task)
    return task.comments


@router.post("/{task_id}/comments", response_model=CommentRead, status_code=201)
def add_comment(
    task_id: str,
    comment_in: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _get_task_or_404(db, task_id)
    assert_can_view_task(current_user, task)
    comment = TaskComment(task_id=task.id, author_id=current_user.id, body=comment_in.body)
    db.add(comment)
    record_audit(db, task, current_user, AuditAction.COMMENTED, comment_in.body[:120])
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/{task_id}/audit", response_model=list[AuditEntryRead])
def list_audit_entries(
    task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    task = _get_task_or_404(db, task_id)
    assert_can_view_task(current_user, task)
    return (
        db.query(TaskAuditEntry)
        .filter(TaskAuditEntry.task_id == task_id)
        .order_by(TaskAuditEntry.created_at)
        .all()
    )
