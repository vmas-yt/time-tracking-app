import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Role, RolePermissionAuditEntry, User


def record_permission_change(
    db: Session, role: Role, actor: User, before: set[str], after: set[str]
) -> None:
    """RBAC Round B3, Decision 2 (§2.4/§6.2): diffs the requested permission
    set against the role's current one and writes one `RolePermissionAuditEntry`
    row per changed key, all sharing one `batch_id` generated once for this
    call. Writes nothing if the diff is empty — re-submitting the same set is
    a no-op, not a loggable event. Caller (`PUT /roles/{id}/permissions`) is
    responsible for actually replacing the role's `RolePermission` rows and
    committing; this only adds audit rows to the same session.
    """
    added = after - before
    removed = before - after
    if not added and not removed:
        return

    batch_id = str(uuid.uuid4())
    now = datetime.utcnow()
    for key in added:
        db.add(
            RolePermissionAuditEntry(
                role_id=role.id,
                actor_id=actor.id,
                batch_id=batch_id,
                permission_key=key,
                change_type="added",
                occurred_at=now,
            )
        )
    for key in removed:
        db.add(
            RolePermissionAuditEntry(
                role_id=role.id,
                actor_id=actor.id,
                batch_id=batch_id,
                permission_key=key,
                change_type="removed",
                occurred_at=now,
            )
        )
