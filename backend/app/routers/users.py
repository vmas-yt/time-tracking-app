from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.database import get_db
from app.deps import get_current_user
from app.models import User, UserRole
from app.schemas import (
    PasswordChangeRequest,
    PasswordResetRequest,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.authz import assert_admin
from app.services.users import deactivate_user, is_last_active_admin, validate_manager_id

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
    if not (include_inactive and current_user.role == UserRole.ADMIN):
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

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=hash_password(user_in.password),
        role=user_in.role,
        manager_id=user_in.manager_id,
        is_active=True,
    )
    db.add(user)
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

    if "email" in updates and updates["email"] != user.email:
        if db.query(User).filter(User.email == updates["email"], User.id != user_id).first():
            raise HTTPException(status_code=400, detail="Email already registered")

    if "manager_id" in updates:
        validate_manager_id(db, updates["manager_id"], target_user_id=user_id)

    for field, value in updates.items():
        setattr(user, field, value)

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
