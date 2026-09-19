from fastapi import HTTPException, status

from app.models import Permission, Task, TimeEntry, User, UserRole


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


def has_permission(user: User, permission: Permission) -> bool:
    """Non-floor permission check for a granted custom-role capability.

    Mirrors assert_admin's floor check for the "admin has everything"
    shortcut (checks the legacy `user.role` column directly, not
    `role_key()`) so this always agrees with the one guarantee that must
    never depend on the new role/permission system being correct. Beyond
    that shortcut, this is purely additive: it can only grant capability a
    custom role was explicitly given via `PUT /roles/{id}/permissions`
    (§2.4), never take anything away from an existing hardcoded check.

    Builtin non-admin roles (employee/manager) always return False here for
    every key, since they can never hold RolePermission rows (§2.4) — their
    behavior is unaffected by this function's existence.
    """
    if user.role == UserRole.ADMIN:
        return True
    if user.role_id is None or user.assigned_role is None:
        return False
    return any(p.permission_key == permission.value for p in user.assigned_role.permissions)


def can_view_task(current_user: User, task: Task) -> bool:
    if current_user.role == UserRole.ADMIN:
        return True
    if current_user.id in (task.assignee_id, task.created_by_id):
        return True
    if task.assignee and task.assignee.manager_id == current_user.id:
        return True
    if has_permission(current_user, Permission.VIEW_ALL_TASKS):   # NEW — appended last
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


def can_control_time_entry(current_user: User, entry: TimeEntry) -> bool:
    """Whether current_user may pause/resume/stop this time entry.

    The ordinary case is identical to can_edit_task on the entry's task
    (floor admin, assignee, or creator) -- checked first, unconditionally,
    exactly as today. The only addition is a narrow, time-entry-scoped
    operational override: a role holding view_all_time_entries may also
    pause/resume/stop *any* entry, without that permission leaking into
    general task edit/delete rights, which stay gated by the untouched
    can_edit_task above.
    """
    if can_edit_task(current_user, entry.task):
        return True
    return has_permission(current_user, Permission.VIEW_ALL_TIME_ENTRIES)


def assert_can_control_time_entry(current_user: User, entry: TimeEntry) -> None:
    if not can_control_time_entry(current_user, entry):
        raise HTTPException(status_code=403, detail="Not authorized to control this time entry")


def assert_admin(current_user: User) -> None:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


def assert_has_permission(current_user: User, permission: Permission) -> None:
    """The `has_permission()` equivalent of `assert_admin` -- raises the same
    `403` shape for every call site converted per the design doc's §3.1
    table (`departments.py`/`teams.py`/`projects.py`/`admin.py`/`tasks.py`'s
    archive endpoints). Not itself a floor function: `has_permission` already
    returns `True` unconditionally for a real admin, so this is a strict
    superset of what the `assert_admin` call it replaces used to allow.
    """
    if not has_permission(current_user, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to perform this action")
