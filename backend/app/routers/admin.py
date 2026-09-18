from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    BoardConfig,
    CustomFieldDefinition,
    CustomFieldType,
    DropdownOption,
    DropdownOptionScope,
    User,
    UserRole,
)
from app.schemas import (
    BoardConfigRead,
    BoardConfigUpdate,
    CustomFieldCreate,
    CustomFieldRead,
    CustomFieldUpdate,
    DropdownOptionCreate,
    DropdownOptionRead,
    DropdownOptionUpdate,
)
from app.services.authz import assert_admin

router = APIRouter(prefix="/admin", tags=["admin"])


def _serialize_option(option: DropdownOption) -> DropdownOptionRead:
    return DropdownOptionRead.model_validate(option)


def _parse_scope(raw: str | None) -> DropdownOptionScope:
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="scope is required and must be one of task_category|task_priority|custom_field",
        )
    try:
        return DropdownOptionScope(raw)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="scope must be one of task_category|task_priority|custom_field",
        )


def _validate_scope_and_field(
    db: Session, scope: DropdownOptionScope, custom_field_id: str | None
) -> str | None:
    """Shared scope/custom_field_id cross-validation for list/create (§2.7).
    Returns the (possibly normalized-to-None) custom_field_id to use."""
    if scope == DropdownOptionScope.CUSTOM_FIELD:
        if not custom_field_id:
            raise HTTPException(
                status_code=400, detail="custom_field_id is required when scope=custom_field"
            )
        field = db.get(CustomFieldDefinition, custom_field_id)
        if not field:
            raise HTTPException(
                status_code=400, detail="custom_field_id does not reference an existing custom field"
            )
        if field.field_type != CustomFieldType.SELECT:
            raise HTTPException(
                status_code=400, detail="custom_field_id must reference a select-type field"
            )
        return custom_field_id

    if custom_field_id is not None:
        raise HTTPException(
            status_code=400, detail="custom_field_id is only valid when scope=custom_field"
        )
    return None


def _serialize_field(db: Session, field: CustomFieldDefinition) -> CustomFieldRead:
    options = None
    if field.field_type == CustomFieldType.SELECT:
        rows = (
            db.query(DropdownOption)
            .filter(
                DropdownOption.scope == DropdownOptionScope.CUSTOM_FIELD,
                DropdownOption.custom_field_id == field.id,
            )
            .order_by(DropdownOption.position)
            .all()
        )
        options = [_serialize_option(o) for o in rows]
    return CustomFieldRead(
        id=field.id,
        name=field.name,
        field_type=field.field_type,
        options=options,
        created_at=field.created_at,
    )


@router.get("/board-config", response_model=BoardConfigRead)
def get_board_config(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    config = db.get(BoardConfig, "default")
    if not config:
        config = BoardConfig(id="default")
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.patch("/board-config", response_model=BoardConfigRead)
def update_board_config(
    update: BoardConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    config = db.get(BoardConfig, "default")
    if not config:
        config = BoardConfig(id="default")
        db.add(config)
    config.swimlane_field = update.swimlane_field
    db.commit()
    db.refresh(config)
    return config


@router.get("/custom-fields", response_model=list[CustomFieldRead])
def list_custom_fields(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [_serialize_field(db, f) for f in db.query(CustomFieldDefinition).all()]


@router.post("/custom-fields", response_model=CustomFieldRead, status_code=201)
def create_custom_field(
    field_in: CustomFieldCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    field = CustomFieldDefinition(name=field_in.name, field_type=field_in.field_type)
    db.add(field)
    db.flush()
    if field_in.options:
        for position, opt in enumerate(field_in.options):
            db.add(
                DropdownOption(
                    scope=DropdownOptionScope.CUSTOM_FIELD,
                    custom_field_id=field.id,
                    value=opt,
                    label=opt,
                    is_builtin=False,
                    is_active=True,
                    position=position,
                )
            )
    db.commit()
    db.refresh(field)
    return _serialize_field(db, field)


@router.patch("/custom-fields/{field_id}", response_model=CustomFieldRead)
def update_custom_field(
    field_id: str,
    update: CustomFieldUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    field = db.get(CustomFieldDefinition, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Custom field not found")

    updates = update.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(field, key, value)

    db.commit()
    db.refresh(field)
    return _serialize_field(db, field)


@router.delete("/custom-fields/{field_id}", status_code=204)
def delete_custom_field(
    field_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    assert_admin(current_user)
    field = db.get(CustomFieldDefinition, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Custom field not found")
    # Cascades to TaskCustomValue and DropdownOption rows via the ORM
    # relationships on CustomFieldDefinition (cascade="all, delete-orphan").
    db.delete(field)
    db.commit()


# ---- Dropdown options -------------------------------------------------------
# See docs/design/custom-fields-admin-design.md §2.7.


@router.get("/dropdown-options", response_model=list[DropdownOptionRead])
def list_dropdown_options(
    scope: str | None = Query(None),
    custom_field_id: str | None = Query(None),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scope_enum = _parse_scope(scope)
    resolved_field_id = _validate_scope_and_field(db, scope_enum, custom_field_id)

    query = db.query(DropdownOption).filter(
        DropdownOption.scope == scope_enum,
        DropdownOption.custom_field_id == resolved_field_id,
    )
    if not (include_inactive and current_user.role == UserRole.ADMIN):
        query = query.filter(DropdownOption.is_active.is_(True))
    options = query.order_by(DropdownOption.position).all()
    return [_serialize_option(o) for o in options]


@router.post("/dropdown-options", response_model=DropdownOptionRead, status_code=201)
def create_dropdown_option(
    option_in: DropdownOptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    scope_enum = _parse_scope(option_in.scope)
    resolved_field_id = _validate_scope_and_field(db, scope_enum, option_in.custom_field_id)

    existing = (
        db.query(DropdownOption)
        .filter(
            DropdownOption.scope == scope_enum,
            DropdownOption.custom_field_id == resolved_field_id,
            DropdownOption.value == option_in.value,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400, detail=f"Option '{option_in.value}' already exists for this scope"
        )

    max_position = (
        db.query(func.max(DropdownOption.position))
        .filter(
            DropdownOption.scope == scope_enum,
            DropdownOption.custom_field_id == resolved_field_id,
        )
        .scalar()
    )
    option = DropdownOption(
        scope=scope_enum,
        custom_field_id=resolved_field_id,
        value=option_in.value,
        label=option_in.label or option_in.value,
        is_builtin=False,
        is_active=True,
        position=(max_position + 1) if max_position is not None else 0,
    )
    db.add(option)
    db.commit()
    db.refresh(option)
    return _serialize_option(option)


def _assert_not_builtin_deactivation(option: DropdownOption) -> None:
    if not option.is_builtin:
        return
    if option.scope == DropdownOptionScope.TASK_CATEGORY and option.value == "other":
        raise HTTPException(
            status_code=409,
            detail=(
                "Others is required by the category_other_text mechanism and cannot be removed"
            ),
        )
    raise HTTPException(status_code=409, detail="Cannot remove a built-in option")


@router.patch("/dropdown-options/{option_id}", response_model=DropdownOptionRead)
def update_dropdown_option(
    option_id: str,
    update: DropdownOptionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    option = db.get(DropdownOption, option_id)
    if not option:
        raise HTTPException(status_code=404, detail="Dropdown option not found")

    if update.is_active is False:
        _assert_not_builtin_deactivation(option)

    if update.label is not None:
        option.label = update.label
    if update.is_active is not None:
        option.is_active = update.is_active
    if update.position is not None:
        option.position = update.position

    db.commit()
    db.refresh(option)
    return _serialize_option(option)


@router.delete("/dropdown-options/{option_id}", response_model=DropdownOptionRead)
def delete_dropdown_option(
    option_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Despite the verb, soft-deactivates (sets is_active=False) — same
    rationale as `DELETE /users/{id}` in the auth-rbac design (§2.7)."""
    assert_admin(current_user)
    option = db.get(DropdownOption, option_id)
    if not option:
        raise HTTPException(status_code=404, detail="Dropdown option not found")

    _assert_not_builtin_deactivation(option)

    option.is_active = False
    db.commit()
    db.refresh(option)
    return _serialize_option(option)
