from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Department, Permission, Team, User
from app.schemas import DepartmentCreate, DepartmentRead, DepartmentUpdate
from app.services.authz import assert_has_permission, has_permission

router = APIRouter(prefix="/departments", tags=["departments"])

_DUPLICATE_NAME_DETAIL = "A department with this name already exists"


@router.get("", response_model=list[DepartmentRead])
def list_departments(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Any authenticated user may list departments (Departments/Teams sidebar,
    Users table's team picker). `include_inactive=true` is admin-only; a
    non-admin passing it has it silently ignored — same precedent as
    `GET /users?include_inactive`."""
    query = db.query(Department)
    if not (include_inactive and has_permission(current_user, Permission.MANAGE_DEPARTMENTS)):
        query = query.filter(Department.is_active.is_(True))
    return query.all()


@router.post("", response_model=DepartmentRead, status_code=status.HTTP_201_CREATED)
def create_department(
    department_in: DepartmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_has_permission(current_user, Permission.MANAGE_DEPARTMENTS)
    if db.query(Department).filter(Department.name == department_in.name).first():
        raise HTTPException(status_code=400, detail=_DUPLICATE_NAME_DETAIL)

    department = Department(name=department_in.name)
    db.add(department)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=_DUPLICATE_NAME_DETAIL)
    db.refresh(department)
    return department


@router.patch("/{department_id}", response_model=DepartmentRead)
def update_department(
    department_id: str,
    update: DepartmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_has_permission(current_user, Permission.MANAGE_DEPARTMENTS)
    department = db.get(Department, department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    updates = update.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] != department.name:
        if (
            db.query(Department)
            .filter(Department.name == updates["name"], Department.id != department_id)
            .first()
        ):
            raise HTTPException(status_code=400, detail=_DUPLICATE_NAME_DETAIL)

    for field, value in updates.items():
        setattr(department, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=_DUPLICATE_NAME_DETAIL)
    db.refresh(department)
    return department


@router.delete("/{department_id}", response_model=DepartmentRead)
def delete_department(
    department_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Despite the verb, soft-deactivates (sets is_active=False) rather than
    hard-deleting — same rationale as `DELETE /users/{id}` and
    `DELETE /admin/dropdown-options/{id}`. 409 if any active Team still
    lives under this department; those must be reassigned/deactivated
    first — same shape as `DELETE /projects/{id}`'s has-tasks guard."""
    assert_has_permission(current_user, Permission.MANAGE_DEPARTMENTS)
    department = db.get(Department, department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    has_active_teams = (
        db.query(Team)
        .filter(Team.department_id == department_id, Team.is_active.is_(True))
        .first()
        is not None
    )
    if has_active_teams:
        raise HTTPException(
            status_code=409,
            detail="Cannot deactivate a department with active teams linked to it.",
        )

    department.is_active = False
    db.commit()
    db.refresh(department)
    return department
