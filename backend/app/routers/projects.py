from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Permission, Project, Task, User
from app.schemas import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.authz import assert_has_permission

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Project).all()


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(
    project_in: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_has_permission(current_user, Permission.MANAGE_PROJECTS)
    project = Project(**project_in.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str,
    update: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_has_permission(current_user, Permission.MANAGE_PROJECTS)
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    updates = update.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    assert_has_permission(current_user, Permission.MANAGE_PROJECTS)
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    has_tasks = db.query(Task).filter(Task.project_id == project_id).first() is not None
    if has_tasks:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a project with tasks linked to it.",
        )
    db.delete(project)
    db.commit()
