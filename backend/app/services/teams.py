from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Department, Team, User, UserRole


def validate_department_id(db: Session, department_id: str | None) -> None:
    """400 if a non-null department_id doesn't reference an existing
    Department, mirroring `services/tasks.py::validate_project_exists`'s
    style. No active check here — reassigning a team's department is an
    admin action independent of whether that department is currently
    accepting new teams."""
    if not department_id:
        return
    department = db.get(Department, department_id)
    if not department:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="department_id does not reference an existing department",
        )


def validate_team_id(db: Session, team_id: str | None) -> None:
    """400 if a non-null team_id doesn't reference an existing, *active*
    Team — used wherever a user or task's team_id is set directly by a
    caller (routers/users.py, routers/tasks.py). Mirrors
    `services/users.py::validate_assignee_active`'s "must be active" style."""
    if not team_id:
        return
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="team_id does not reference an existing team",
        )
    if not team.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot assign to an inactive team",
        )


def validate_team_manager_id(db: Session, manager_id: str | None) -> None:
    """Shared `Team.manager_id` validation, mirroring
    `services/users.py::validate_manager_id`'s style for `POST /users`/
    `PATCH /users/{id}`. No self-reference check here — that check exists
    there only because a *user* can't be their own manager; a *team* has no
    analogous notion of self-reference.
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
            detail="Cannot assign a deactivated user as a team manager",
        )
    if manager.role == UserRole.EMPLOYEE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="manager_id must reference a user with role 'manager' or 'admin'",
        )


def sync_team_manager(db: Session, team: Team) -> None:
    """Cascade `team.manager_id` onto every current member's `User.manager_id`
    cache column.

    `Team.manager_id` is authoritative going forward; `User.manager_id` (what
    `services/authz.py`, `routers/reports.py`, and `routers/notifications.py`
    all key their manager-scoped queries off of, unchanged by this round) is
    kept correct for any user who has a `team_id` purely by calling this
    function any time that could have gone stale:

      * after `team.manager_id` itself changes (re-syncs every member), or
      * after a user's `team_id` is set/changed to point at `team` (re-syncs
        every member, including the one just added/moved — a no-op for
        everyone else already in sync).

    A user with `team_id is None` is never touched here (legacy path: their
    `manager_id` stays whatever an admin last set it to directly — see the
    note on `User.manager_id` in models.py).

    Deliberately does not commit — callers own the transaction (matching
    `services/tasks.py`'s `record_audit`/`record_status_event`/`change_status`
    convention of mutating within the caller's existing session and letting
    the router commit once, after every related change for the request).

    Wired in from two call sites (Round B): `routers/teams.py::create_team`/
    `update_team` (after `team.manager_id` changes) and
    `routers/users.py::create_user`/`update_user` (after a user's `team_id`
    is set/changed to a non-null value). Callers must `db.flush()` first if
    the change this call is meant to pick up (the team's own `manager_id`,
    or a user's just-set `team_id`) hasn't been flushed yet — this issues a
    raw bulk `UPDATE` against the `users` table, not the ORM's in-memory
    state, so it only sees what's already been flushed within the
    transaction.
    """
    db.query(User).filter(User.team_id == team.id).update(
        {User.manager_id: team.manager_id}, synchronize_session=False
    )
