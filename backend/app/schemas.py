from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models import TaskStatus, TimerStatus


class UserBase(BaseModel):
    email: EmailStr
    full_name: str


class UserCreate(UserBase):
    password: str


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    is_admin: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProjectBase(BaseModel):
    name: str
    description: str | None = None


class ProjectCreate(ProjectBase):
    pass


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class TaskBase(BaseModel):
    title: str
    description: str | None = None
    project_id: str
    assignee_id: str | None = None
    status: TaskStatus = TaskStatus.BACKLOG
    position: int = 0


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    assignee_id: str | None = None
    status: TaskStatus | None = None
    position: int | None = None


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class TimeEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    user_id: str
    status: TimerStatus
    started_at: datetime
    last_resumed_at: datetime | None
    accumulated_seconds: float
    ended_at: datetime | None
    elapsed_seconds: float = 0.0
