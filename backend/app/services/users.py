from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import AuditAction, TimeEntry, TimerStatus, User, UserRole
from app.services.tasks import record_audit
from app.services.timer import pause_entry


def validate_manager_id(db: Session, manager_id: str | None, target_user_id: str | None) -> None:
    """Shared `manager_id` validation for `POST /users` and `PATCH
    /users/{id}` (see docs/design/auth-rbac-design.md §7.2). `target_user_id`
    is the id of the user being created/edited (None for a brand-new user,
    whose id doesn't exist yet — the self-reference check is skipped then).
    """
    if manager_id is None:
        return

    manager = db.get(User, manager_id)
    if not manager:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="manager_id does not reference an existing user",
        )
    if not manager.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot assign a deactivated user as a manager",
        )
    if target_user_id is not None and manager_id == target_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user cannot be their own manager",
        )
    if manager.role == UserRole.EMPLOYEE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="manager_id must reference a user with role 'manager' or 'admin'",
        )


def validate_assignee_active(db: Session, assignee_id: str | None) -> None:
    """Reject (400) assigning a task to a deactivated user (§6.5). No
    existence check here by design — that's a separate, pre-existing gap
    this change doesn't take on."""
    if not assignee_id:
        return
    assignee = db.get(User, assignee_id)
    if assignee is not None and not assignee.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot assign a task to a deactivated user",
        )


def is_last_active_admin(db: Session, user: User) -> bool:
    if user.role != UserRole.ADMIN or not user.is_active:
        return False
    active_admins = (
        db.query(User).filter(User.role == UserRole.ADMIN, User.is_active.is_(True)).count()
    )
    return active_admins == 1


def would_strip_last_active_admin(db: Session, user: User, new_role: UserRole | None) -> bool:
    """True iff setting `user.role` to `new_role` would leave the system
    with zero active admins.

    The floor this guards is anchored to the legacy `role` enum column
    forever, by design (see the note on `User.role` in models.py):
    `assert_admin` (services/authz.py) checks `user.role == UserRole.ADMIN`
    directly and never anything routed through `role_id`/`roles`/
    `role_permissions`. So the only way to "lock everyone out" at that
    floor is for the sole remaining row with `role == ADMIN` (and
    `is_active`) to stop satisfying that condition — whether by
    deactivation (already guarded by `is_last_active_admin`, used by
    `deactivate_user` below) or by its `role` column changing to anything
    else, including `None`.

    `new_role` is `None` both for "the caller is explicitly setting `role`
    to `NULL`" (newly representable now that Round B2's migration makes
    `users.role` nullable — see `services/migrations.py::
    _migrate_users_role_nullable`) and, incidentally, for "no role was
    specified" if a caller passes `None` as a sentinel; either way, `None`
    is not `UserRole.ADMIN`, so both cases are correctly treated as
    "would strip admin" for whoever currently holds the floor. There is no
    reachable path yet (Round B3's job) that assigns a *custom* role in
    place of a builtin one, but this function is written to already be
    correct for that case rather than needing revisiting then.
    """
    if new_role == UserRole.ADMIN:
        return False
    return is_last_active_admin(db, user)


def deactivate_user(db: Session, user: User, actor: User) -> User:
    """Soft-delete a user (§6.4): 409 if this would remove the only active
    admin; otherwise flips `is_active`/`deactivated_at` and auto-pauses any
    of the user's RUNNING timers (mirroring the manual On-Hold auto-pause in
    `services/tasks.py::change_status`), never auto-stopping them since the
    underlying work isn't necessarily done just because this person left.
    """
    if user.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot deactivate your own account.",
        )
    if is_last_active_admin(db, user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot deactivate the only remaining admin account.",
        )

    user.is_active = False
    user.deactivated_at = datetime.utcnow()

    running_entries = (
        db.query(TimeEntry)
        .filter(TimeEntry.user_id == user.id, TimeEntry.status == TimerStatus.RUNNING)
        .all()
    )
    for entry in running_entries:
        pause_entry(entry)
        record_audit(
            db,
            entry.task,
            actor,
            AuditAction.TIMER_PAUSED,
            "Timer auto-paused (user deactivated)",
        )

    db.commit()
    db.refresh(user)
    return user
