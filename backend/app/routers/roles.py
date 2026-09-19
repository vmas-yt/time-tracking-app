import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.deps import get_current_user
from app.models import Role, RolePermission, RolePermissionAuditEntry, User
from app.schemas import (
    RoleAuditActor,
    RoleCreate,
    RolePermissionAuditEntryRead,
    RolePermissionsUpdate,
    RoleRead,
    RoleUpdate,
)
from app.services.authz import assert_admin
from app.services.roles import record_permission_change

router = APIRouter(prefix="/roles", tags=["roles"])

_MAX_KEY_LENGTH = 64


def _slugify(name: str) -> str:
    """§2.2's slug algorithm: lowercase, non-alnum runs -> single `-`, trim
    leading/trailing `-`, cap at 64 chars."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:_MAX_KEY_LENGTH]


def _generate_unique_key(db: Session, name: str) -> str:
    """On collision with an existing `Role.key`, append `-2`, `-3`, ... until
    unique (§2.2). `key` is server-generated only, never client-settable."""
    base = _slugify(name) or "role"
    candidate = base
    suffix = 2
    while db.query(Role).filter(Role.key == candidate).first() is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _serialize_role(role: Role) -> RoleRead:
    return RoleRead(
        id=role.id,
        key=role.key,
        name=role.name,
        is_builtin=role.is_builtin,
        permission_keys=sorted(p.permission_key for p in role.permissions),
        created_at=role.created_at,
    )


def _assert_name_not_blank(name: str) -> None:
    if not name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name must not be blank")


@router.get("", response_model=list[RoleRead])
def list_roles(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Open-read (§2.1) — any authenticated user, same precedent as
    `GET /departments`/`GET /teams`. Eager-loads `permissions` (found as an
    N+1 in senior-qa's Round B3 verification pass) so `_serialize_role`'s
    per-role access doesn't trigger one extra query per row."""
    roles = (
        db.query(Role)
        .options(joinedload(Role.permissions))
        .order_by(Role.created_at)
        .all()
    )
    return [_serialize_role(r) for r in roles]


@router.post("", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
    role_in: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_admin(current_user)
    _assert_name_not_blank(role_in.name)

    role = Role(
        key=_generate_unique_key(db, role_in.name),
        name=role_in.name,
        is_builtin=False,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return _serialize_role(role)


@router.patch("/{role_id}", response_model=RoleRead)
def update_role(
    role_id: str,
    update: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rename only (§2.3) — `key`/`is_builtin` are immutable after creation."""
    assert_admin(current_user)
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_builtin:
        raise HTTPException(status_code=409, detail="Cannot rename a built-in role.")
    _assert_name_not_blank(update.name)

    role.name = update.name
    db.commit()
    db.refresh(role)
    return _serialize_role(role)


@router.put("/{role_id}/permissions", response_model=RoleRead)
def update_role_permissions(
    role_id: str,
    update: RolePermissionsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full-set replacement (§2.4) — not incremental add/remove. Writes an
    audit record of exactly what changed (Decision 2, §6.2), sharing one
    `batch_id` per call; no rows are written if the diff is empty."""
    assert_admin(current_user)
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_builtin:
        raise HTTPException(
            status_code=409,
            detail="Built-in roles cannot hold explicit permission grants.",
        )

    before = {p.permission_key for p in role.permissions}
    after = {p.value for p in update.permission_keys}

    record_permission_change(db, role, current_user, before, after)

    # Full-set replacement (§2.4): delete every existing row, then insert the
    # new set, as two explicit steps rather than reassigning `role.permissions`
    # to a fresh list in one shot. The unique constraint on
    # `(role_id, permission_key)` means a key present in *both* the old and
    # new set (e.g. keeping `view_all_tasks` while swapping `manage_teams`
    # for `manage_projects`) can otherwise trip a `UNIQUE constraint failed`
    # if the ORM's unit-of-work happens to emit the new row's INSERT before
    # the old row's DELETE — an explicit `db.flush()` between the two forces
    # the ordering.
    for existing in list(role.permissions):
        db.delete(existing)
    db.flush()
    for key in after:
        db.add(RolePermission(role_id=role.id, permission_key=key))

    db.commit()
    db.refresh(role)
    return _serialize_role(role)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Real hard delete (§2.5), not soft-deactivate — a `Role` has no
    downstream historical dependents once truly unoccupied. Guarded by:
    built-in immutability, an occupancy check against *every* `User` row
    (active and inactive — §6.3's deliberate divergence from the
    Team/Department precedent, since a hard delete is real FK-enforced on
    Postgres regardless of `is_active`), and a has-audit-history check (once
    a custom role's permissions have ever been changed, it can never be
    deleted again, only renamed/emptied/unassigned)."""
    assert_admin(current_user)
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_builtin:
        raise HTTPException(status_code=409, detail="Cannot delete a built-in role.")

    has_any_holder = db.query(User).filter(User.role_id == role_id).first() is not None
    if has_any_holder:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a role assigned to one or more users. Reassign them first.",
        )

    has_audit_history = (
        db.query(RolePermissionAuditEntry)
        .filter(RolePermissionAuditEntry.role_id == role_id)
        .first()
        is not None
    )
    if has_audit_history:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot delete a role with permission-change history — it would erase "
                "the audit trail."
            ),
        )

    db.delete(role)
    db.commit()


@router.get("/{role_id}/audit", response_model=list[RolePermissionAuditEntryRead])
def get_role_audit(
    role_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin-only (§2.7), gated by `assert_admin()` directly, never
    `has_permission()` — reading who-changed-what-permissions stays exactly
    as delegable as managing roles is, i.e. not at all in this round.
    Built-in roles always `200` -> `[]` (they can never hold `RolePermission`
    rows or generate audit rows), not a `404`/`409`."""
    assert_admin(current_user)
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    rows = (
        db.query(RolePermissionAuditEntry)
        .filter(RolePermissionAuditEntry.role_id == role_id)
        .order_by(RolePermissionAuditEntry.occurred_at)
        .all()
    )

    batches: dict[str, dict] = {}
    for row in rows:
        batch = batches.setdefault(
            row.batch_id,
            {"occurred_at": row.occurred_at, "actor_id": row.actor_id, "added": [], "removed": []},
        )
        if row.change_type == "added":
            batch["added"].append(row.permission_key)
        else:
            batch["removed"].append(row.permission_key)

    actor_ids = {b["actor_id"] for b in batches.values()}
    actors = {u.id: u for u in db.query(User).filter(User.id.in_(actor_ids)).all()} if actor_ids else {}

    entries = [
        RolePermissionAuditEntryRead(
            batch_id=batch_id,
            occurred_at=batch["occurred_at"],
            actor=RoleAuditActor(
                id=batch["actor_id"],
                full_name=actors[batch["actor_id"]].full_name if batch["actor_id"] in actors else "",
                email=actors[batch["actor_id"]].email if batch["actor_id"] in actors else "",
            ),
            added=batch["added"],
            removed=batch["removed"],
        )
        for batch_id, batch in batches.items()
    ]
    entries.sort(key=lambda e: e.occurred_at, reverse=True)
    return entries
