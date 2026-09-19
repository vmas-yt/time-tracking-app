from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Permission, Task, TaskStatus, TaskStatusEvent, User
from app.schemas import (
    CumulativeFlowPoint,
    CycleTimePoint,
    LeadTimePoint,
    ThroughputBucket,
)
from app.services.authz import has_permission

router = APIRouter(prefix="/reports", tags=["reports"])


def _scope_to_visible_tasks(query, current_user: User):
    """Role-based task-set scoping (design doc §10): employee sees tasks
    they're the assignee or creator of; manager additionally sees tasks
    assigned to their direct reports; admin sees everything. Copies the
    existing `GET /tasks` filter and the `notifications.py::reminder_candidates`
    direct-reports-only precedent — no recursive manager-chain traversal."""
    if has_permission(current_user, Permission.VIEW_REPORTS_ALL):
        return query
    return query.filter(
        or_(
            Task.assignee_id == current_user.id,
            Task.created_by_id == current_user.id,
            Task.assignee.has(User.manager_id == current_user.id),
        )
    )


def _completed_tasks(db: Session, project_id: str | None, current_user: User):
    query = db.query(Task).filter(
        Task.status == TaskStatus.COMPLETED,
        Task.completed_at.isnot(None),
        Task.archived_at.is_(None),
    )
    if project_id:
        query = query.filter(Task.project_id == project_id)
    query = _scope_to_visible_tasks(query, current_user)
    return query.all()


@router.get("/cycle-time", response_model=list[CycleTimePoint])
def cycle_time(project_id: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Time from a task's first entry into In Progress to Completed."""
    points = []
    for task in _completed_tasks(db, project_id, current_user):
        if not task.first_in_progress_at:
            continue
        seconds = (task.completed_at - task.first_in_progress_at).total_seconds()
        points.append(
            CycleTimePoint(
                task_id=task.id,
                title=task.title,
                started_at=task.first_in_progress_at,
                completed_at=task.completed_at,
                cycle_time_seconds=seconds,
            )
        )
    return sorted(points, key=lambda p: p.completed_at)


@router.get("/control-chart", response_model=list[CycleTimePoint])
def control_chart(project_id: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Same data as cycle-time: each completed task plotted at its
    completion date, sized by cycle time — the classic control chart view."""
    return cycle_time(project_id, db, current_user)


@router.get("/lead-time", response_model=list[LeadTimePoint])
def lead_time(project_id: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Time from task creation to Completed."""
    points = []
    for task in _completed_tasks(db, project_id, current_user):
        # A manually-logged task's completed_at is the user-supplied
        # Completion Date, which can be backdated before created_at (the
        # real row-insertion time) -- that would otherwise produce
        # negative/near-zero lead-time values and corrupt this report.
        # Cycle Time excludes these tasks "for free" via its own
        # `if not task.first_in_progress_at` guard below, since a manual
        # task never has an In Progress period at all.
        if task.is_manual_entry:
            continue
        seconds = (task.completed_at - task.created_at).total_seconds()
        points.append(
            LeadTimePoint(
                task_id=task.id,
                title=task.title,
                created_at=task.created_at,
                completed_at=task.completed_at,
                lead_time_seconds=seconds,
            )
        )
    return sorted(points, key=lambda p: p.completed_at)


@router.get("/throughput", response_model=list[ThroughputBucket])
def throughput(
    project_id: str | None = None,
    interval: str = Query("day", pattern="^(day|week)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Count of tasks completed per day or week."""
    buckets: dict[str, int] = defaultdict(int)
    for task in _completed_tasks(db, project_id, current_user):
        completed = task.completed_at
        if interval == "week":
            period_start = (completed - timedelta(days=completed.weekday())).date()
        else:
            period_start = completed.date()
        buckets[period_start.isoformat()] += 1
    return [
        ThroughputBucket(period_start=k, completed_count=v)
        for k, v in sorted(buckets.items())
    ]


@router.get("/cumulative-flow", response_model=list[CumulativeFlowPoint])
def cumulative_flow(
    project_id: str | None = None,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Count of tasks in each status, snapshotted at the end of each day
    over the trailing window, replayed from the task status event log."""
    query = (
        db.query(TaskStatusEvent)
        .join(Task)
        .filter(Task.archived_at.is_(None))
        .order_by(TaskStatusEvent.occurred_at)
    )
    if project_id:
        query = query.filter(Task.project_id == project_id)
    query = _scope_to_visible_tasks(query, current_user)
    events = query.all()

    if not events:
        return []

    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days - 1)

    task_status: dict[str, TaskStatus] = {}
    event_idx = 0
    results: list[CumulativeFlowPoint] = []

    current_date = start_date
    while current_date <= end_date:
        end_of_day = datetime.combine(current_date, datetime.max.time())
        while event_idx < len(events) and events[event_idx].occurred_at <= end_of_day:
            event = events[event_idx]
            task_status[event.task_id] = event.to_status
            event_idx += 1

        counts: dict[str, int] = defaultdict(int)
        for status_value in task_status.values():
            counts[status_value.value] += 1

        results.append(CumulativeFlowPoint(date=current_date.isoformat(), counts=dict(counts)))
        current_date += timedelta(days=1)

    return results
