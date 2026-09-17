from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    AuditAction,
    CustomFieldDefinition,
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
from app.services.authz import assert_can_edit_task, assert_can_view_task
from app.services.tasks import change_status, record_audit, record_status_event

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _custom_values_map(db: Session, task_id: str) -> dict[str, str]:
    rows = db.query(TaskCustomValue).filter(TaskCustomValue.task_id == task_id).all()
    return {row.field_id: row.value for row in rows}


def _serialize(db: Session, task: Task) -> TaskRead:
    data = TaskRead.model_validate(task)
    data.custom_values = _custom_values_map(db, task.id)
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List tasks for the board.

    `manager_id` returns tasks assigned to anyone whose `manager_id` equals
    the given user — the "my team" board a line manager needs, without one
    round-trip per direct report. Non-admins are additionally restricted to
    tasks they can view (assignee, creator, or their assignee's manager),
    matching `services/authz.assert_can_view_task` used elsewhere.
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
    task = Task(
        **task_in.model_dump(),
        created_by_id=current_user.id,
        status=TaskStatus.BACKLOG,
    )
    if task.assignee_id is None:
        task.assignee_id = current_user.id
    db.add(task)
    db.flush()
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

    if updates:
        for field, value in updates.items():
            setattr(task, field, value)
        record_audit(
            db, task, current_user, AuditAction.UPDATED, f"Updated fields: {', '.join(updates.keys())}"
        )

    if task_in.custom_values:
        for field_id, value in task_in.custom_values.items():
            field_def = db.get(CustomFieldDefinition, field_id)
            if not field_def:
                raise HTTPException(status_code=400, detail=f"Unknown custom field '{field_id}'")
            existing = (
                db.query(TaskCustomValue)
                .filter(TaskCustomValue.task_id == task.id, TaskCustomValue.field_id == field_id)
                .first()
            )
            if existing:
                existing.value = value
            else:
                db.add(TaskCustomValue(task_id=task.id, field_id=field_id, value=value))
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
