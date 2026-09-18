from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Team, User, UserRole


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

    Not yet called from anywhere in this round (Round A) — the team CRUD
    surface that would call it (creating/editing a team, or moving a user
    between teams) is `routers/teams.py`, added in a later round. Wiring
    this in is that round's job; this function is the schema-adjacent piece
    that belongs to db-admin.
    """
    db.query(User).filter(User.team_id == team.id).update(
        {User.manager_id: team.manager_id}, synchronize_session=False
    )
