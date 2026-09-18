from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    AuditAction,
    DropdownOptionScope,
    Task,
    TaskAuditEntry,
    TaskComment,
    TaskCustomValue,
    TaskStatus,
    TimeEntry,
    User,
    UserRole,
)
from app.schemas import (
    AuditEntryRead,
    CommentCreate,
    CommentRead,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)
from app.services.authz import assert_admin, assert_can_edit_task, assert_can_view_task
from app.services.tasks import (
    apply_custom_values,
    change_status,
    record_audit,
    record_status_event,
    total_logged_seconds,
    validate_dropdown_value,
    validate_project_exists,
)
from app.services.teams import validate_team_id
from app.services.users import validate_assignee_active

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _custom_values_map(db: Session, task_id: str) -> dict[str, str]:
    rows = db.query(TaskCustomValue).filter(TaskCustomValue.task_id == task_id).all()
    return {row.field_id: row.value for row in rows}


def _serialize(db: Session, task: Task) -> TaskRead:
    data = TaskRead.model_validate(task)
    data.custom_values = _custom_values_map(db, task.id)
    data.total_logged_seconds = total_logged_seconds(db, task)
    return data


def _get_task_or_404(db: Session, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
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
    if not (include_archived and current_user.role == UserRole.ADMIN):
        query = query.filter(Task.archived_at.is_(None))
    if current_user.role != UserRole.ADMIN:
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
    validate_assignee_active(db, task_in.assignee_id)
    validate_project_exists(db, task_in.project_id)
    validate_dropdown_value(db, DropdownOptionScope.TASK_CATEGORY, task_in.category)
    validate_dropdown_value(db, DropdownOptionScope.TASK_PRIORITY, task_in.priority)
    if task_in.team_id is not None:
        validate_team_id(db, task_in.team_id)

    task_data = task_in.model_dump(exclude={"custom_values"})
    task = Task(
        **task_data,
        created_by_id=current_user.id,
        status=TaskStatus.BACKLOG,
    )
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
    db.add(task)
    db.flush()
    if task_in.custom_values:
        apply_custom_values(db, task, task_in.custom_values)
    record_audit(db, task, current_user, AuditAction.CREATED, f"Task created: {task.title}")
    record_status_event(db, task, current_user, None, TaskStatus.BACKLOG)
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
    assert_admin(current_user)
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
    assert_admin(current_user)
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
