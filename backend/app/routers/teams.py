from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import BoardConfig, Permission, SwimlaneField, Team, TeamBoardConfig, User
from app.schemas import TeamBoardConfigRead, TeamBoardConfigUpdate, TeamCreate, TeamRead, TeamUpdate
from app.services.authz import assert_has_permission, has_permission
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
    if not (include_inactive and has_permission(current_user, Permission.MANAGE_TEAMS)):
        query = query.filter(Team.is_active.is_(True))
    return query.all()


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
def create_team(
    team_in: TeamCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_has_permission(current_user, Permission.MANAGE_TEAMS)
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
    assert_has_permission(current_user, Permission.MANAGE_TEAMS)
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
    assert_has_permission(current_user, Permission.MANAGE_TEAMS)
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


def _get_team_or_404(db: Session, team_id: str) -> Team:
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _get_or_create_team_board_config(db: Session, team_id: str) -> TeamBoardConfig:
    """Lazy-create-if-missing, identical idiom to
    `routers/admin.py::get_board_config`'s handling of the `id="default"`
    singleton. Per db-admin's recommendation (design doc §7.4) a
    newly-created row defaults `swimlane_field` to the *current* global
    `board_config.swimlane_field` value rather than a hardcoded
    `SwimlaneField.ASSIGNEE` -- consistent with what
    `_migrate_team_board_config_backfill` already does for every
    pre-existing team, so a team created between backfill runs and its
    first board view doesn't land on a different default than its
    siblings."""
    config = db.get(TeamBoardConfig, team_id)
    if not config:
        global_config = db.get(BoardConfig, "default")
        default_field = global_config.swimlane_field if global_config else SwimlaneField.ASSIGNEE
        config = TeamBoardConfig(team_id=team_id, swimlane_field=default_field)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/{team_id}/board-config", response_model=TeamBoardConfigRead)
def get_team_board_config(
    team_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Any authenticated user may read this — mirrors `GET
    /admin/board-config`'s open-read and `GET /teams`'s open-read; a team's
    swim-lane grouping/board name is not sensitive (Round C, design doc
    §4.1)."""
    _get_team_or_404(db, team_id)
    config = _get_or_create_team_board_config(db, team_id)
    data = TeamBoardConfigRead.model_validate(config)
    data.can_manage = has_permission(current_user, Permission.MANAGE_BOARD_CONFIG)
    return data


@router.patch("/{team_id}/board-config", response_model=TeamBoardConfigRead)
def update_team_board_config(
    team_id: str,
    update: TeamBoardConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Gated by the same global `MANAGE_BOARD_CONFIG` permission as `PATCH
    /admin/board-config` — admin-only, generalized as-is, deliberately no
    team-manager carve-out (design doc §5.2, finalized)."""
    assert_has_permission(current_user, Permission.MANAGE_BOARD_CONFIG)
    _get_team_or_404(db, team_id)
    config = _get_or_create_team_board_config(db, team_id)

    updates = update.model_dump(exclude_unset=True)
    if "swimlane_field" in updates and updates["swimlane_field"] is None:
        # Unlike board_name (nullable, explicit null is a legitimate "clear
        # back to the Team.name fallback" per §4.2), swimlane_field is a
        # NOT NULL column (same as the existing global BoardConfigUpdate) —
        # there is no "clear" semantics for it. An omitted key leaves it
        # unchanged; an explicit null is a client error, not a valid value.
        raise HTTPException(status_code=422, detail="swimlane_field cannot be null")
    for field, value in updates.items():
        setattr(config, field, value)

    db.commit()
    db.refresh(config)
    data = TeamBoardConfigRead.model_validate(config)
    data.can_manage = True   # caller just passed the assert_has_permission check above
    return data
