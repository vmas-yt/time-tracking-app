from fastapi import HTTPException, status

from app.models import Task, User, UserRole


def can_view_task(current_user: User, task: Task) -> bool:
    if current_user.role == UserRole.ADMIN:
        return True
    if current_user.id in (task.assignee_id, task.created_by_id):
        return True
    if task.assignee and task.assignee.manager_id == current_user.id:
        return True
    return False


def assert_can_view_task(current_user: User, task: Task) -> None:
    if not can_view_task(current_user, task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this task")


def assert_admin(current_user: User) -> None:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
