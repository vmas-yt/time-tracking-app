from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Team, User, UserRole
from app.schemas import TeamCreate, TeamRead, TeamUpdate
from app.services.authz import assert_admin
from app.services.teams import sync_team_manager, validate_department_id, validate_team_manager_id

router = APIRouter(prefix="/teams", tags=["teams"])

_DUPLICATE_NAME_DETAIL = "A team with this name already exists in this department"


@router.get("", response_model=list[TeamRead])
def list_teams(
    department_id: str | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Any authenticated user may list teams. `include_inactive=true` is
    admin-only-effect, same precedent as `GET /users?include_inactive` and
    `GET /departments?include_inactive`."""
    query = db.query(Team)
    if department_id:
        query = query.filter(Team.department_id == department_id)
    if not (include_inactive and current_user.role == UserRole.ADMIN):
        query = query.filter(Team.is_active.is_(True))
    return query.all()


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
def create_team(
    team_in: TeamCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    validate_department_id(db, team_in.department_id)
    validate_team_manager_id(db, team_in.manager_id)

    team = Team(
        name=team_in.name,
        department_id=team_in.department_id,
        manager_id=team_in.manager_id,
    )
    db.add(team)

    if team.manager_id is not None:
        # team.id's UUID default is applied at flush time, not at object
        # construction — without this flush, team.id is still None here,
        # so sync_team_manager's `User.team_id == team.id` filter would
        # compile to `team_id IS NULL`, mass-reassigning manager_id onto
        # every unplaced user in the system instead of this (currently
        # empty) team's members. Otherwise a no-op for a brand-new team —
        # called anyway for consistency with update_team's call site below,
        # rather than special-casing "empty team".
        db.flush()
        sync_team_manager(db, team)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=_DUPLICATE_NAME_DETAIL)
    db.refresh(team)
    return team


@router.patch("/{team_id}", response_model=TeamRead)
def update_team(
    team_id: str,
    update: TeamUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    updates = update.model_dump(exclude_unset=True)
    if "department_id" in updates:
        validate_department_id(db, updates["department_id"])
    if "manager_id" in updates:
        validate_team_manager_id(db, updates["manager_id"])

    manager_changed = "manager_id" in updates and updates["manager_id"] != team.manager_id

    for field, value in updates.items():
        setattr(team, field, value)

    if manager_changed:
        # The one call site that actually wires sync_team_manager's
        # cascade onto every current member's User.manager_id — must run
        # before the commit below, per services/teams.py's contract.
        sync_team_manager(db, team)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=_DUPLICATE_NAME_DETAIL)
    db.refresh(team)
    return team


@router.delete("/{team_id}", response_model=TeamRead)
def delete_team(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Despite the verb, soft-deactivates rather than hard-deleting — same
    rationale as `DELETE /departments/{id}`. 409 if any active User still
    has this team_id; those must be reassigned/deactivated first."""
    assert_admin(current_user)
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    has_active_members = (
        db.query(User).filter(User.team_id == team_id, User.is_active.is_(True)).first() is not None
    )
    if has_active_members:
        raise HTTPException(
            status_code=409,
            detail="Cannot deactivate a team with active members assigned to it.",
        )

    team.is_active = False
    db.commit()
    db.refresh(team)
    return team
