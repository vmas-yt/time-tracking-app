from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PlainSerializer, model_validator

from app.models import (
    AuditAction,
    CustomFieldType,
    DropdownOptionScope,
    SwimlaneField,
    TaskStatus,
    TaskType,
    TimerStatus,
    UserRole,
)


def _serialize_utc(dt: datetime) -> str:
    """All stored datetimes come from datetime.utcnow() (naive, but UTC).
    Serialized bare, a client's `new Date(...)` parses that string as local
    time rather than UTC, shifting every timestamp by the viewer's UTC
    offset. Stamping the 'Z' suffix here — rather than switching every
    datetime.utcnow() call and DateTime column to be timezone-aware, a much
    larger change for the same DB-level result — makes the wire format
    unambiguous without touching how times are stored.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UTCDatetime = Annotated[datetime, PlainSerializer(_serialize_utc, return_type=str, when_used="json")]


class UTCModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Users ----------------------------------------------------------------


class UserBase(BaseModel):
    email: EmailStr
    full_name: str


class UserCreate(UserBase):
    role: UserRole = UserRole.EMPLOYEE
    manager_id: str | None = None
    password: str = Field(min_length=8)


class UserRead(UserBase, UTCModel):
    id: str
    role: UserRole
    manager_id: str | None
    is_active: bool
    deactivated_at: UTCDatetime | None = None
    created_at: UTCDatetime


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    role: UserRole | None = None
    manager_id: str | None = None
    is_active: bool | None = None


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- Projects ---------------------------------------------------------------


class ProjectBase(BaseModel):
    name: str
    description: str | None = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectRead(ProjectBase, UTCModel):
    id: str
    created_at: UTCDatetime


# ---- Tasks ------------------------------------------------------------------


class TaskBase(BaseModel):
    title: str
    description: str | None = None
    project_id: str | None = None
    assignee_id: str | None = None
    task_type: TaskType = TaskType.NORMAL
    # category/priority are plain, DB-validated strings now (see
    # docs/design/custom-fields-admin-design.md §2.8) — the fixed-enum
    # Pydantic type is gone; the valid set is enforced at the service layer
    # (services/tasks.py::validate_dropdown_value) against live DropdownOption
    # rows, not the OpenAPI schema.
    category: str = Field(min_length=1)
    category_other_text: str | None = None
    priority: str = "normal"

    @model_validator(mode="after")
    def _validate_other_text(self):
        if self.category == "other" and not self.category_other_text:
            raise ValueError("category_other_text is required when category is 'other'")
        return self


class TaskCreate(TaskBase):
    custom_values: dict[str, str] | None = None


class TaskUpdate(BaseModel):
    """Manual field/status edits. IN_PROGRESS and COMPLETED are reached only
    through the timer endpoints, not through this endpoint."""

    title: str | None = None
    description: str | None = None
    project_id: str | None = None
    assignee_id: str | None = None
    category: str | None = None
    category_other_text: str | None = None
    priority: str | None = None
    position: int | None = None
    status: TaskStatus | None = None
    custom_values: dict[str, str] | None = None


class TaskRead(TaskBase, UTCModel):
    id: str
    created_by_id: str
    status: TaskStatus
    position: int
    created_at: UTCDatetime
    updated_at: UTCDatetime
    completed_at: UTCDatetime | None
    archived_at: UTCDatetime | None = None
    custom_values: dict[str, str] = {}
    total_logged_seconds: float = 0.0


# ---- Comments & audit trail ---------------------------------------------------


class CommentCreate(BaseModel):
    body: str


class CommentRead(UTCModel):
    id: str
    task_id: str
    author_id: str
    body: str
    created_at: UTCDatetime


class AuditEntryRead(UTCModel):
    id: str
    task_id: str
    actor_id: str
    action: AuditAction
    detail: str
    created_at: UTCDatetime


# ---- Time entries -------------------------------------------------------------


class TimeEntryRead(UTCModel):
    id: str
    task_id: str
    user_id: str
    status: TimerStatus
    started_at: UTCDatetime
    last_resumed_at: UTCDatetime | None
    accumulated_seconds: float
    ended_at: UTCDatetime | None
    elapsed_seconds: float = 0.0


# ---- Dropdown options & custom fields & board config ---------------------------


class DropdownOptionRead(UTCModel):
    id: str
    scope: DropdownOptionScope
    custom_field_id: str | None
    value: str
    label: str
    is_builtin: bool
    is_active: bool
    position: int
    created_at: UTCDatetime


# The shape of one entry in CustomFieldRead.options. Distinguished by name
# from DropdownOptionRead per the design doc's frontend contract (§1.4's
# `CustomFieldOption` interface), but identical in fields today since a
# custom field's options are just its DropdownOption rows.
CustomFieldOptionRead = DropdownOptionRead


class DropdownOptionCreate(BaseModel):
    # `scope` is a plain string (not DropdownOptionScope) so an invalid value
    # can be rejected with an explicit 400 in the router rather than a 422
    # from Pydantic enum coercion (see docs/design/custom-fields-admin-design.md §2.7).
    scope: str
    custom_field_id: str | None = None
    value: str
    label: str | None = None


class DropdownOptionUpdate(BaseModel):
    label: str | None = None
    is_active: bool | None = None
    position: int | None = None


class CustomFieldCreate(BaseModel):
    name: str
    field_type: CustomFieldType
    options: list[str] | None = None


class CustomFieldUpdate(BaseModel):
    # field_type is deliberately not editable here — changing a field's data
    # type after real task values exist is a separate, riskier problem.
    name: str | None = None


class CustomFieldRead(UTCModel):
    id: str
    name: str
    field_type: CustomFieldType
    options: list[CustomFieldOptionRead] | None = None
    created_at: UTCDatetime


class BoardConfigRead(UTCModel):
    swimlane_field: SwimlaneField
    updated_at: UTCDatetime


class BoardConfigUpdate(BaseModel):
    swimlane_field: SwimlaneField


# ---- Reporting -----------------------------------------------------------------


class CycleTimePoint(UTCModel):
    task_id: str
    title: str
    started_at: UTCDatetime
    completed_at: UTCDatetime
    cycle_time_seconds: float


class LeadTimePoint(UTCModel):
    task_id: str
    title: str
    created_at: UTCDatetime
    completed_at: UTCDatetime
    lead_time_seconds: float


class ThroughputBucket(BaseModel):
    period_start: str
    completed_count: int


class CumulativeFlowPoint(BaseModel):
    date: str
    counts: dict[str, int]


class ReminderCandidate(UTCModel):
    user_id: str
    full_name: str
    email: str
    manager_id: str | None
    last_logged_at: UTCDatetime | None
