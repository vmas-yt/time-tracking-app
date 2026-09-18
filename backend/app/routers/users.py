from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.database import get_db
from app.deps import get_current_user
from app.models import Team, User
from app.schemas import (
    PasswordChangeRequest,
    PasswordResetRequest,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.authz import assert_admin, role_key
from app.services.teams import sync_team_manager, validate_team_id
from app.services.users import (
    deactivate_user,
    is_last_active_admin,
    role_id_for_builtin_role,
    validate_manager_id,
    would_strip_last_active_admin,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("", response_model=list[UserRead])
def list_users(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Excludes deactivated users by default so they stop appearing in
    assignee/manager pickers. `include_inactive=true` is admin-only; a
    non-admin passing it has it silently ignored rather than erroring."""
    query = db.query(User)
    if not (include_inactive and role_key(current_user) == "admin"):
        query = query.filter(User.is_active.is_(True))
    return query.all()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    if db.query(User).filter(User.email == user_in.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    validate_manager_id(db, user_in.manager_id, target_user_id=None)
    validate_team_id(db, user_in.team_id)

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=hash_password(user_in.password),
        role=user_in.role,
        role_id=role_id_for_builtin_role(db, user_in.role),
        manager_id=user_in.manager_id,
        team_id=user_in.team_id,
        is_active=True,
    )
    db.add(user)
    if user.team_id is not None:
        # Flush first so the just-added row is visible to
        # sync_team_manager's raw bulk UPDATE (autoflush is off — see
        # app/database.py). Picks up the team's current manager_id
        # immediately, whatever the request sent for manager_id (see the
        # note on User.manager_id in models.py).
        db.flush()
        team = db.get(Team, user.team_id)
        sync_team_manager(db, team)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_own_password(
    payload: PasswordChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: str,
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: str,
    update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    updates = update.model_dump(exclude_unset=True)
    is_active_target = updates.pop("is_active", None)

    # Checked against the user's *current* role/status, before any other
    # field in this same request is applied below — otherwise a combined
    # payload like {"role": "employee", "is_active": false} would change the
    # role first and let the last-active-admin guard check a role that's
    # already been vacated, silently bypassing it.
    deactivating = is_active_target is False and user.is_active
    if deactivating and user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot deactivate your own account.",
        )
    if deactivating and is_last_active_admin(db, user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot deactivate the only remaining admin account.",
        )

    # Same "check before applying anything" rule as the deactivation guard
    # above, and the same floor: the only row satisfying `assert_admin`'s
    # `role == ADMIN` check can't be reassigned away from it (including to
    # `None`, now representable at all since `users.role` became nullable —
    # see services/migrations.py::_migrate_users_role_nullable) while it's
    # the system's sole active admin. `"role" in updates` (not `.get(...)`)
    # so an explicit `{"role": null}` is caught the same as any other value
    # — a request that simply doesn't mention `role` at all must never hit
    # this branch.
    if "role" in updates and would_strip_last_active_admin(db, user, updates["role"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot change the role of the only remaining admin account.",
        )

    if "email" in updates and updates["email"] != user.email:
        if db.query(User).filter(User.email == updates["email"], User.id != user_id).first():
            raise HTTPException(status_code=400, detail="Email already registered")

    if "manager_id" in updates:
        validate_manager_id(db, updates["manager_id"], target_user_id=user_id)
    if "team_id" in updates:
        validate_team_id(db, updates["team_id"])

    for field, value in updates.items():
        setattr(user, field, value)

    if "role" in updates:
        # RBAC Round B2's reachable sync direction (role -> role_id, see the
        # note on User.role_id in models.py): `role` is currently the only
        # API-facing field that ever changes which role a user holds, so
        # this keeps `role_id` from going stale relative to it. An explicit
        # `{"role": null}` (newly representable now that `role` is
        # nullable) has no matching builtin row, so `role_id` follows it to
        # null too, rather than being left pointing at a now-wrong role.
        user.role_id = role_id_for_builtin_role(db, updates["role"]) if updates["role"] is not None else None

    if "team_id" in updates and updates["team_id"] is not None:
        # Same rationale as create_user: sync immediately whenever team_id
        # is set/changed to a non-null value, so the member picks up the
        # team's manager_id right away rather than staying stale until the
        # next unrelated team edit. Whatever manager_id this same request
        # may also have sent gets overwritten by this — see the note on
        # User.manager_id in models.py.
        db.flush()
        team = db.get(Team, updates["team_id"])
        sync_team_manager(db, team)
    elif "team_id" in updates and updates["team_id"] is None and "manager_id" not in updates:
        # Detaching from a team: manager_id was a derived cache of that
        # team's manager (sync_team_manager), not something an admin set
        # directly. Leaving it in place would silently freeze it at the old
        # team's manager — the detached user would keep showing up in that
        # manager's reports/reminders (both keyed on manager_id) with no
        # admin having actually chosen that. Clear it so the legacy
        # directly-editable state (per the note on User.manager_id in
        # models.py) starts from an honest null instead of a stale cached
        # value. If this same request also explicitly sends manager_id,
        # that's respected instead — already applied via the setattr loop
        # above, so this branch only fires when it wasn't sent.
        user.manager_id = None

    if deactivating:
        deactivate_user(db, user, current_user)
    elif is_active_target is True and not user.is_active:
        user.is_active = True
        user.deactivated_at = None

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", response_model=UserRead)
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Despite the DELETE verb, this soft-deletes (deactivates) the user
    rather than removing the row — see docs/design/auth-rbac-design.md §6."""
    assert_admin(current_user)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return deactivate_user(db, user, current_user)
