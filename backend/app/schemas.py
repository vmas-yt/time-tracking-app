from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

from app.models import (
    AuditAction,
    CustomFieldType,
    SwimlaneField,
    TaskCategory,
    TaskPriority,
    TaskStatus,
    TaskType,
    TimerStatus,
    UserRole,
)

# ---- Users ----------------------------------------------------------------


class UserBase(BaseModel):
    email: EmailStr
    full_name: str


class UserCreate(UserBase):
    password: str


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: UserRole
    manager_id: str | None
    created_at: datetime


class UserUpdate(BaseModel):
    role: UserRole | None = None
    manager_id: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- Projects ---------------------------------------------------------------


class ProjectBase(BaseModel):
    name: str
    description: str | None = None


class ProjectCreate(ProjectBase):
    pass


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


# ---- Tasks ------------------------------------------------------------------


class TaskBase(BaseModel):
    title: str
    description: str | None = None
    project_id: str | None = None
    assignee_id: str | None = None
    task_type: TaskType = TaskType.NORMAL
    category: TaskCategory
    category_other_text: str | None = None
    priority: TaskPriority = TaskPriority.NORMAL

    @model_validator(mode="after")
    def _validate_other_text(self):
        if self.category == TaskCategory.OTHER and not self.category_other_text:
            raise ValueError("category_other_text is required when category is 'other'")
        return self


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    """Manual field/status edits. IN_PROGRESS and COMPLETED are reached only
    through the timer endpoints, not through this endpoint."""

    title: str | None = None
    description: str | None = None
    assignee_id: str | None = None
    category: TaskCategory | None = None
    category_other_text: str | None = None
    priority: TaskPriority | None = None
    position: int | None = None
    status: TaskStatus | None = None
    custom_values: dict[str, str] | None = None


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_by_id: str
    status: TaskStatus
    position: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    custom_values: dict[str, str] = {}


# ---- Comments & audit trail ---------------------------------------------------


class CommentCreate(BaseModel):
    body: str


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    author_id: str
    body: str
    created_at: datetime


class AuditEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    actor_id: str
    action: AuditAction
    detail: str
    created_at: datetime


# ---- Time entries -------------------------------------------------------------


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


# ---- Custom fields & board config ---------------------------------------------


class CustomFieldCreate(BaseModel):
    name: str
    field_type: CustomFieldType
    options: list[str] | None = None


class CustomFieldRead(BaseModel):
    id: str
    name: str
    field_type: CustomFieldType
    options: list[str] | None = None
    created_at: datetime


class BoardConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    swimlane_field: SwimlaneField
    updated_at: datetime


class BoardConfigUpdate(BaseModel):
    swimlane_field: SwimlaneField


# ---- Reporting -----------------------------------------------------------------


class CycleTimePoint(BaseModel):
    task_id: str
    title: str
    started_at: datetime
    completed_at: datetime
    cycle_time_seconds: float


class LeadTimePoint(BaseModel):
    task_id: str
    title: str
    created_at: datetime
    completed_at: datetime
    lead_time_seconds: float


class ThroughputBucket(BaseModel):
    period_start: str
    completed_count: int


class CumulativeFlowPoint(BaseModel):
    date: str
    counts: dict[str, int]


class ReminderCandidate(BaseModel):
    user_id: str
    full_name: str
    email: str
    manager_id: str | None
    last_logged_at: datetime | None
