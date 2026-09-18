import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, text
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
    # Manual/retroactive time-logging feature. This column is a *native*
    # Postgres ENUM (see `TaskAuditEntry.action`'s `Enum(AuditAction)`, which
    # never sets `native_enum=False`) -- adding this member is therefore not
    # a no-op on Postgres the way it is on SQLite. See
    # services/migrations.py::_migrate_audit_action_add_manual_time_logged
    # for the required `ALTER TYPE ... ADD VALUE` step, verified empirically
    # against real Postgres 16 (not assumed) per this project's own
    # near-miss history.
    MANUAL_TIME_LOGGED = "manual_time_logged"


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


class DropdownOptionScope(str, enum.Enum):
    TASK_CATEGORY = "task_category"
    TASK_PRIORITY = "task_priority"
    CUSTOM_FIELD = "custom_field"


class Role(Base):
    """RBAC Round B1 (additive schema only). Exactly 3 rows are seeded as
    builtins by services/migrations.py::_migrate_rbac_schema_backfill --
    `key` in ("employee", "manager", "admin"), matching the legacy `UserRole`
    enum values. Custom (non-builtin) roles are a later round's (B3) job;
    this table's shape already accommodates them (`is_builtin=False`) but
    nothing creates one yet.

    Admin's permissions are implicit/all-permissions-always in application
    code by design, not stored `role_permissions` rows -- see that table's
    docstring.
    """

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class RolePermission(Base):
    """One granted permission for a role. `permission_key` is validated
    against an in-code permission enum at the application layer in a later
    round (B3) -- deliberately not a DB-level catalog/FK table here, just a
    plain string column, per solution-architect's design for this round.

    Admin is never represented here: its permissions are "all permissions,
    always" in application code, not enumerated rows -- an Admin role with
    zero `role_permissions` rows is correct and expected, not a bug.
    """

    __tablename__ = "role_permissions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False)
    permission_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("uq_role_permission_role_key", "role_id", "permission_key", unique=True),
    )

    role: Mapped["Role"] = relationship(back_populates="permissions")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    # RBAC Round B2: relaxed from NOT NULL. Deprecated, best-effort legacy
    # mirror going forward -- kept in sync with `role_id` by application code
    # for a user who holds a *builtin* role (see the note on `role_id`
    # below), but has no valid value to hold for a user assigned a genuinely
    # custom role (Round B3), so it becomes NULL for that user instead.
    # `assert_admin` (services/authz.py) and the last-active-admin floor
    # (services/users.py::is_last_active_admin/deactivate_user) keep reading
    # *this* column directly forever, by design -- never `role_id`/`roles`/
    # `role_permissions` -- see services/migrations.py's
    # `_migrate_users_role_nullable` for the migration (including its
    # rollback-plan writeup) that made this column nullable on an
    # already-deployed database, on both backends.
    role: Mapped[UserRole | None] = mapped_column(Enum(UserRole), default=UserRole.EMPLOYEE, nullable=True)
    # `manager_id` is the field `authz.py`/`reports.py`/`notifications.py` key
    # off of for review/reminder scoping. For a user with a `team_id`, this
    # becomes a derived, auto-synced cache of that team's `Team.manager_id`
    # (see services/teams.py::sync_team_manager) — Team.manager_id is
    # authoritative going forward. For a user with `team_id = None`, this
    # column stays directly admin-editable exactly as before (legacy path).
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Org structure (department -> team). Nullable is a permanent, legitimate
    # state (a not-yet-placed new hire), not just a pre-migration marker —
    # see services/migrations.py::_migrate_org_structure_backfill for why the
    # bootstrap-team backfill is careful never to overwrite a null set after
    # the fact.
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    # RBAC Round B1 (additive schema only) added this column, backfilled from
    # the legacy `role` enum via services/migrations.py::
    # _migrate_rbac_schema_backfill. Round B2 (authorization half) is the
    # cutover: every non-floor authorization/visibility check now reads this
    # column (via `services/authz.py::role_key`) instead of `role` directly.
    # The floor itself (`assert_admin`, `can_view_task`, `can_edit_task` in
    # services/authz.py; `is_last_active_admin`/`would_strip_last_active_admin`
    # in services/users.py) is the deliberate, permanent exception -- see the
    # note on `role` above. Kept in sync with `role` going forward by
    # `create_user`/`update_user` (routers/users.py) whenever `role` is set,
    # since no API-facing field lets a caller set `role_id` independently yet
    # (that's Round B3's custom-role picker) -- see
    # services/users.py::role_id_for_builtin_role.
    role_id: Mapped[str | None] = mapped_column(ForeignKey("roles.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    manager: Mapped["User | None"] = relationship(remote_side="User.id")
    # RBAC Round B2 (authorization half): the relationship the `role_id`
    # column's own docstring above left for this round to name, now that
    # this round is the one actually reading it (`services/authz.py::
    # role_key`). Named `assigned_role` rather than `role` since the legacy
    # enum column already owns that name on this model.
    assigned_role: Mapped["Role | None"] = relationship(foreign_keys=[role_id])
    team: Mapped["Team | None"] = relationship(back_populates="members", foreign_keys=[team_id])
    assigned_tasks: Mapped[list["Task"]] = relationship(
        back_populates="assignee", foreign_keys="Task.assignee_id"
    )
    time_entries: Mapped[list["TimeEntry"]] = relationship(back_populates="user")


class Department(Base):
    """Top level of the Department -> Team org structure (Round A)."""

    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    teams: Mapped[list["Team"]] = relationship(back_populates="department")


class Team(Base):
    """A team within a department. `manager_id` is authoritative for the
    team's line-manager relationship going forward — see the note on
    `User.manager_id` and `services/teams.py::sync_team_manager`."""

    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # `use_alter`/`name=` breaks the Team<->User circular FK dependency
    # (Team.manager_id -> users.id, User.team_id -> teams.id) so
    # `Base.metadata.create_all` can create both tables without raising
    # `CircularDependencyError` on a fresh database. Verified directly
    # against both backends: on Postgres this defers to a separate `ALTER
    # TABLE teams ADD CONSTRAINT ... FOREIGN KEY` issued after every table
    # is created (real, enforced constraint); on SQLite (which has no
    # `ALTER TABLE ADD CONSTRAINT` at all) SQLAlchemy instead inlines the
    # forward-referencing FK directly into `CREATE TABLE teams`, which
    # SQLite accepts without error since it never validates FK targets at
    # `CREATE TABLE`/DDL time regardless — consistent with this project's
    # existing FK columns already being unenforced on SQLite (no
    # `PRAGMA foreign_keys=ON` is set anywhere in app/database.py).
    manager_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_teams_manager_id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("uq_team_department_name", "department_id", "name", unique=True),
    )

    department: Mapped["Department"] = relationship(back_populates="teams")
    manager: Mapped["User | None"] = relationship(foreign_keys=[manager_id])
    members: Mapped[list["User"]] = relationship(back_populates="team", foreign_keys="User.team_id")


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
    # A task's "home" team — independent of its current assignee (Jira/Linear
    # style), set once at creation (defaults to the assignee's team, else the
    # creator's team, else null) and never re-derived if the assignee later
    # changes teams. That defaulting logic lives wherever tasks are created
    # (routers/tasks.py::create_task) — out of scope for this schema-only
    # round; see db-admin's Round A report.
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), nullable=True)

    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType), default=TaskType.NORMAL, nullable=False)
    # category/priority were native DB enums (Enum(TaskCategory)/Enum(TaskPriority));
    # changed to plain String, app-validated against the admin-editable
    # DropdownOption table (see docs/design/custom-fields-admin-design.md §2.3).
    # TaskCategory/TaskPriority are kept above only as the source list for seed
    # data (services/bootstrap.py::ensure_default_dropdown_options), not as a
    # column type or Pydantic field type anymore.
    category: Mapped[str] = mapped_column(String, nullable=False)
    category_other_text: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[str] = mapped_column(String, default="normal", nullable=False)

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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Manual/retroactive time-logging feature. `is_manual_entry` is durable
    # and never changes after being set: manual vs. live-tracked is
    # mutually exclusive and terminal for a given task, used for the
    # "Manually logged" tag on the card/detail view. Every pre-existing
    # task correctly defaults to False -- no historical task was ever
    # manually logged.
    is_manual_entry: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Deliberately a *new* column, not a repurposing of `first_in_progress_at`
    # above: that column is `reports.py::cycle_time`'s source of truth for
    # "this task genuinely sat In Progress", and a manually-logged task never
    # has an In Progress period at all (it jumps straight to Completed) --
    # writing the user-supplied Start Date into `first_in_progress_at` would
    # silently corrupt Cycle Time's meaning by pulling manual tasks into a
    # report about a period they never experienced. Going forward this gets
    # populated from two sources: a live-tracked task gets it set to the same
    # `now` at the exact moment `first_in_progress_at` is first set (see
    # routers/time_entries.py::start_timer), a manually-logged task gets it
    # set directly from the user's supplied Start Date. NULL for every
    # pre-existing row (no backfill) is correct, not a gap: no historical
    # task needs this populated retroactively, and `first_in_progress_at`
    # already exists for old data if it's ever needed.
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project | None"] = relationship(back_populates="tasks")
    assignee: Mapped["User | None"] = relationship(back_populates="assigned_tasks", foreign_keys=[assignee_id])
    team: Mapped["Team | None"] = relationship(foreign_keys=[team_id])
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
    # Manual/retroactive time-logging feature: True only on the synthetic
    # terminal entry a manual log creates. Not an audit-trail field --
    # `TaskAuditEntry` has no FK to `TimeEntry` -- this exists purely so any
    # `TimeEntry`-scoped endpoint/report can filter manual vs. live entries
    # without a join to `Task`. Every pre-existing row correctly defaults to
    # False -- no historical time entry was ever manually logged.
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # SELECT-type option storage moved entirely to DropdownOption rows
    # (scope=custom_field); the old CSV `options` column is dropped. These
    # cascades ensure deleting a field cleans up after itself automatically.
    values: Mapped[list["TaskCustomValue"]] = relationship(
        back_populates="field", cascade="all, delete-orphan"
    )
    dropdown_options: Mapped[list["DropdownOption"]] = relationship(cascade="all, delete-orphan")


class TaskCustomValue(Base):
    __tablename__ = "task_custom_values"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    field_id: Mapped[str] = mapped_column(ForeignKey("custom_field_definitions.id"), nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)

    task: Mapped["Task"] = relationship(back_populates="custom_value_rows")
    field: Mapped["CustomFieldDefinition"] = relationship(back_populates="values")


class DropdownOption(Base):
    """Admin-editable option values for task category, task priority, and
    every SELECT-type custom field, discriminated by `scope`. See
    docs/design/custom-fields-admin-design.md §2.3."""

    __tablename__ = "dropdown_options"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    scope: Mapped[DropdownOptionScope] = mapped_column(Enum(DropdownOptionScope), nullable=False)
    custom_field_id: Mapped[str | None] = mapped_column(
        ForeignKey("custom_field_definitions.id"), nullable=True
    )  # set iff scope == CUSTOM_FIELD; null for task_category/task_priority
    value: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index(
            "uq_dropdown_option_scope_value",
            "scope",
            "custom_field_id",
            "value",
            unique=True,
        ),
    )


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


class ManualTimeEntrySettings(Base):
    """Singleton row (id='default') for the admin-editable manual/retroactive
    time-logging policy -- same singleton pattern as `BoardConfig` above, but
    deliberately kept as its own table rather than folded into `BoardConfig`
    itself: that table is mid-restructuring in a separate, not-yet-built
    round (team-scoped boards), and entangling a brand-new org-wide policy
    setting with a table about to change shape would create needless
    coupling. Brand-new table -- `Base.metadata.create_all` creates it with
    zero migration code needed, same as any other new table; no
    `ensure_schema_migrations` step exists (or is needed) for it.
    """

    __tablename__ = "manual_time_entry_settings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: "default")
    max_days_back: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
