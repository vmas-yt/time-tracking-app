from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.database import get_db
from app.deps import get_current_user
from app.models import Team, User, UserRole
from app.schemas import (
    PasswordChangeRequest,
    PasswordResetRequest,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.authz import assert_admin
from app.services.teams import sync_team_manager, validate_team_id
from app.services.users import (
    deactivate_user,
    is_last_active_admin,
    resolve_role_assignment,
    validate_manager_id,
    would_strip_last_active_admin,
)

router = APIRouter(prefix="/users", tags=["users"])


def _role_display_name(user: User) -> str:
    """RBAC Round B3 (§4.1): `UserRead.role_name` — resolved display name,
    works uniformly for a builtin or a custom role. Mirrors `role_key`'s own
    `role_id`-first, legacy-`role`-fallback resolution order (see
    `services/authz.py::role_key`'s docstring for why that fallback exists
    at all — a user constructed directly via the ORM, bypassing both
    `POST /users` and the migration backfill, as several test fixtures do)."""
    if user.role_id is not None and user.assigned_role is not None:
        return user.assigned_role.name
    if user.role is not None:
        return user.role.value.capitalize()
    return ""


def _serialize(user: User) -> UserRead:
    data = UserRead.model_validate(user)
    data.role_name = _role_display_name(user)
    return data


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)):
    return _serialize(current_user)


@router.get("", response_model=list[UserRead])
def list_users(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Excludes deactivated users by default so they stop appearing in
    assignee/manager pickers. `include_inactive=true` is open to any
    authenticated user (not admin-gated): a deactivated user's name/email
    isn't sensitive, and every viewer with legitimate access to a task,
    comment, or audit-trail entry needs to be able to resolve its
    assignee/author/actor's real name even after that person is
    deactivated — restricting this to admins silently broke historical
    display (showing "Unassigned" or a raw user id) for every non-admin
    viewer, which is the exact regression this comment now documents."""
    query = db.query(User)
    if not include_inactive:
        query = query.filter(User.is_active.is_(True))
    return [_serialize(u) for u in query.all()]


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

    resolved_role, resolved_role_id = resolve_role_assignment(db, user_in.role, user_in.role_id)

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=hash_password(user_in.password),
        role=resolved_role,
        role_id=resolved_role_id,
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
    if user.role != resolved_role:
        # SQLAlchemy's Python-side column default (`User.role`'s
        # `default=UserRole.EMPLOYEE`) fires on INSERT whenever the column's
        # value is `None` at flush time -- including when a caller *deliberately*
        # passes `role=None` in the constructor, not just when the field is left
        # unset entirely. RBAC Round B3 is the first caller that ever needs the
        # former (a brand-new user assigned a genuinely custom `role_id` must
        # land with `role` truly NULL, §4.2/§4.4) -- the initial INSERT above
        # silently resurrects `UserRole.EMPLOYEE` instead. A second, explicit
        # UPDATE (which this default does *not* apply to -- verified directly)
        # corrects it. This is a no-op extra round-trip for every other caller,
        # since `resolved_role` already matches what actually got persisted in
        # every case except this one.
        user.role = resolved_role
        db.commit()
        db.refresh(user)
    return _serialize(user)


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

    # RBAC Round B3 (§4.2/§4.3): resolve `role`/`role_id` together, before
    # applying anything else below — same "check before applying" rule as
    # the deactivation guard above. A non-null `role` or a non-null `role_id`
    # resolves through the new role-assignment table; an explicit null on
    # *either* field with the other absent (`{"role": null}` or
    # `{"role_id": null}`) is the pre-existing Round B2 null-out path,
    # preserved byte-for-byte (both columns go to None) rather than being
    # routed through `resolve_role_assignment`'s "neither given" branch,
    # which is create-only (defaults to Employee) and would otherwise make
    # `{"role_id": null}` silently promote the user to Employee instead of
    # nulling out the assignment like `{"role": null}` already does.
    role_in_updates = "role" in updates
    role_id_in_updates = "role_id" in updates
    role_being_changed = role_in_updates or role_id_in_updates
    resolved_role: UserRole | None = None
    resolved_role_id: str | None = None
    explicit_role = role_in_updates and updates.get("role") is not None
    explicit_role_id = role_id_in_updates and updates.get("role_id") is not None
    if explicit_role or explicit_role_id:
        resolved_role, resolved_role_id = resolve_role_assignment(
            db, updates.get("role"), updates.get("role_id")
        )

    # Same floor as before: the only row satisfying `assert_admin`'s
    # `role == ADMIN` check can't be reassigned away from it (including to
    # `None`, now representable at all since `users.role` became nullable —
    # see services/migrations.py::_migrate_users_role_nullable) while it's
    # the system's sole active admin. Checked against the *resolved* role
    # (not the raw request field) so assigning a custom `role_id` — which
    # resolves to `role=None` — is correctly treated as "would strip admin"
    # too, exactly like an explicit `role: null` already was.
    if role_being_changed and would_strip_last_active_admin(db, user, resolved_role):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot change the role of the only remaining admin account.",
        )
    updates.pop("role", None)
    updates.pop("role_id", None)

    if "email" in updates and updates["email"] != user.email:
        if db.query(User).filter(User.email == updates["email"], User.id != user_id).first():
            raise HTTPException(status_code=400, detail="Email already registered")

    if "manager_id" in updates:
        validate_manager_id(db, updates["manager_id"], target_user_id=user_id)
    if "team_id" in updates:
        validate_team_id(db, updates["team_id"])

    for field, value in updates.items():
        setattr(user, field, value)

    if role_being_changed:
        # RBAC Round B3 (§4.2): applies the pair resolved above together, so
        # `role`/`role_id` never go out of sync with each other — whichever
        # of the two the request actually sent.
        user.role = resolved_role
        user.role_id = resolved_role_id

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
    return _serialize(user)


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
    return _serialize(deactivate_user(db, user, current_user))
