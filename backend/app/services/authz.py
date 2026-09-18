from fastapi import HTTPException, status

from app.models import Task, User, UserRole


def role_key(user: User) -> str:
    """The user's role key ("employee"/"manager"/"admin", or a future
    custom role's key) -- the read helper every non-floor authorization/
    visibility check (RBAC Round B2) uses instead of comparing the legacy
    `role` enum column directly.

    Resolves via `user.role_id` -> `Role.key` (the `assigned_role`
    relationship on `User`) when `role_id` is set. Falls back to the legacy
    `user.role.value` if `role_id` is somehow unset -- defensive only: every
    user should have a `role_id` after Round B1's backfill, but this must
    not crash for one that doesn't (e.g. a user constructed directly via the
    ORM, bypassing both `POST /users` and the migration backfill, as several
    tests' fixtures do).

    This is a read helper, not a permission check -- it doesn't decide
    *what* a role can do (that's Round B3's permission system, built on top
    of this). `can_view_task`/`can_edit_task`/`assert_admin` below are the
    floor and deliberately do NOT use this: they keep reading the legacy
    `role` column directly, forever, so an editing mistake in the
    admin-configurable role/permission system this function reads from can
    never accidentally strip the one guarantee that stops a total lockout —
    see the note on `User.role` in models.py.
    """
    if user.role_id is not None and user.assigned_role is not None:
        return user.assigned_role.key
    return user.role.value


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


def can_edit_task(current_user: User, task: Task) -> bool:
    """Assignee, creator, or admin may mutate a task or its timer.

    Deliberately excludes a task's manager — managers review time/tasks per
    the PRD ("review only — no approval step"), they don't edit a report's
    tasks or control their timer.
    """
    if current_user.role == UserRole.ADMIN:
        return True
    return current_user.id in (task.assignee_id, task.created_by_id)


def assert_can_edit_task(current_user: User, task: Task) -> None:
    if not can_edit_task(current_user, task):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to edit this task")


def assert_admin(current_user: User) -> None:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
