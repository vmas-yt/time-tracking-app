from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import BoardConfig, CustomFieldDefinition, User
from app.schemas import BoardConfigRead, BoardConfigUpdate, CustomFieldCreate, CustomFieldRead
from app.services.authz import assert_admin

router = APIRouter(prefix="/admin", tags=["admin"])


def _serialize_field(field: CustomFieldDefinition) -> CustomFieldRead:
    return CustomFieldRead(
        id=field.id,
        name=field.name,
        field_type=field.field_type,
        options=field.options.split(",") if field.options else None,
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
    return [_serialize_field(f) for f in db.query(CustomFieldDefinition).all()]


@router.post("/custom-fields", response_model=CustomFieldRead, status_code=201)
def create_custom_field(
    field_in: CustomFieldCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    field = CustomFieldDefinition(
        name=field_in.name,
        field_type=field_in.field_type,
        options=",".join(field_in.options) if field_in.options else None,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return _serialize_field(field)


@router.delete("/custom-fields/{field_id}", status_code=204)
def delete_custom_field(
    field_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    assert_admin(current_user)
    field = db.get(CustomFieldDefinition, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Custom field not found")
    db.delete(field)
    db.commit()
