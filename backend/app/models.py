import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    ADMIN = "admin"


class TaskType(str, enum.Enum):
    NORMAL = "normal"
    AD_HOC = "ad_hoc"


class TaskCategory(str, enum.Enum):
    PRODUCTION_ISSUE = "production_issue"
    URGENT_REQUEST = "urgent_request"
    MEETING = "meeting"
    SUPPORT_TICKET = "support_ticket"
    CYBER_SECURITY_REQUEST = "cyber_security_request"
    PLATFORM_SUPPORT = "platform_support"
    INFRASTRUCTURE = "infrastructure"
    OTHER = "other"


class TaskPriority(str, enum.Enum):
    NORMAL = "normal"
    EXPEDITE = "expedite"


class TaskStatus(str, enum.Enum):
    """Fixed 5-status workflow per the PRD. IN_PROGRESS and COMPLETED are
    reached only through the timer (start/resume and stop); the other
    transitions go through a manual status change. See
    app/routers/time_entries.py and app/services/tasks.py for the allowed
    transition table.
    """

    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"


class TimerStatus(str, enum.Enum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class AuditAction(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    STATUS_CHANGED = "status_changed"
    COMMENTED = "commented"
    TIMER_STARTED = "timer_started"
    TIMER_PAUSED = "timer_paused"
    TIMER_RESUMED = "timer_resumed"
    TIMER_STOPPED = "timer_stopped"


class CustomFieldType(str, enum.Enum):
    TEXT = "text"
    NUMBER = "number"
    SELECT = "select"
    DATE = "date"
    BOOLEAN = "boolean"


class SwimlaneField(str, enum.Enum):
    ASSIGNEE = "assignee"
    TASK_TYPE = "task_type"
    CATEGORY = "category"
    PRIORITY = "priority"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.EMPLOYEE, nullable=False)
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    manager: Mapped["User | None"] = relationship(remote_side="User.id")
    assigned_tasks: Mapped[list["Task"]] = relationship(
        back_populates="assignee", foreign_keys="Task.assignee_id"
    )
    time_entries: Mapped[list["TimeEntry"]] = relationship(back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tasks: Mapped[list["Task"]] = relationship(back_populates="project")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)

    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType), default=TaskType.NORMAL, nullable=False)
    category: Mapped[TaskCategory] = mapped_column(Enum(TaskCategory), nullable=False)
    category_other_text: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority), default=TaskPriority.NORMAL, nullable=False
    )

    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.BACKLOG, nullable=False
    )
    position: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_in_progress_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project | None"] = relationship(back_populates="tasks")
    assignee: Mapped["User | None"] = relationship(back_populates="assigned_tasks", foreign_keys=[assignee_id])
    time_entries: Mapped[list["TimeEntry"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    comments: Mapped[list["TaskComment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskComment.created_at"
    )
    audit_entries: Mapped[list["TaskAuditEntry"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskAuditEntry.created_at"
    )
    status_events: Mapped[list["TaskStatusEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskStatusEvent.occurred_at"
    )
    custom_value_rows: Mapped[list["TaskCustomValue"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TimeEntry(Base):
    """One timer lifecycle for a user working on a task.

    State machine: RUNNING <-> PAUSED -> STOPPED (terminal). A task may have
    at most one open (RUNNING or PAUSED) entry at a time; a user may have at
    most one RUNNING entry across all their tasks, but several of their
    tasks may sit PAUSED (In Progress paused, or On Hold) simultaneously.
    `accumulated_seconds` banks time from completed running segments;
    `last_resumed_at` is set only while RUNNING.
    """

    __tablename__ = "time_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[TimerStatus] = mapped_column(Enum(TimerStatus), default=TimerStatus.RUNNING)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_resumed_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    accumulated_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # DB-level backstop for the two PRD invariants ("only one open entry per
    # task"; "only one RUNNING timer per user") on top of the query-then-check
    # guards in app/services/timer.py, so two truly concurrent requests can't
    # both slip past the application check and create two open/running rows.
    # SQLAlchemy persists the Python Enum member's *name* (e.g. "RUNNING"),
    # not its lowercase `.value`, hence the uppercase literals here.
    __table_args__ = (
        Index(
            "uq_time_entries_open_per_task",
            "task_id",
            unique=True,
            sqlite_where=text("status != 'STOPPED'"),
            postgresql_where=text("status != 'STOPPED'"),
        ),
        Index(
            "uq_time_entries_running_per_user",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'RUNNING'"),
            postgresql_where=text("status = 'RUNNING'"),
        ),
    )

    task: Mapped["Task"] = relationship(back_populates="time_entries")
    user: Mapped["User"] = relationship(back_populates="time_entries")


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped["Task"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship()


class TaskAuditEntry(Base):
    """Human-readable audit trail, visible to the employee on their own tasks."""

    __tablename__ = "task_audit_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[AuditAction] = mapped_column(Enum(AuditAction), nullable=False)
    detail: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped["Task"] = relationship(back_populates="audit_entries")
    actor: Mapped["User"] = relationship()


class TaskStatusEvent(Base):
    """Structured status-change history — the source of truth for reporting
    (cycle time, lead time, throughput, cumulative flow, control chart)."""

    __tablename__ = "task_status_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    from_status: Mapped[TaskStatus | None] = mapped_column(Enum(TaskStatus), nullable=True)
    to_status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), nullable=False)
    changed_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped["Task"] = relationship(back_populates="status_events")


class CustomFieldDefinition(Base):
    """Admin-defined custom field, applied to all tasks (ClickUp-style)."""

    __tablename__ = "custom_field_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    field_type: Mapped[CustomFieldType] = mapped_column(Enum(CustomFieldType), nullable=False)
    options: Mapped[str | None] = mapped_column(String, nullable=True)  # comma-separated, for SELECT
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaskCustomValue(Base):
    __tablename__ = "task_custom_values"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    field_id: Mapped[str] = mapped_column(ForeignKey("custom_field_definitions.id"), nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)

    task: Mapped["Task"] = relationship(back_populates="custom_value_rows")
    field: Mapped["CustomFieldDefinition"] = relationship()


class BoardConfig(Base):
    """Singleton row (id='default') for the admin-configurable Kanban board."""

    __tablename__ = "board_config"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: "default")
    swimlane_field: Mapped[SwimlaneField] = mapped_column(
        Enum(SwimlaneField), default=SwimlaneField.ASSIGNEE, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
