"""RBAC Round B2 (authorization half): `services/authz.py::role_key` and the
role -> role_id sync direction wired into `routers/users.py`'s
`create_user`/`update_user` (see the note on `User.role_id` in models.py).

These tests deliberately do NOT touch the floor (`assert_admin`,
`can_view_task`, `can_edit_task`, `is_last_active_admin`,
`would_strip_last_active_admin`) — those stay anchored to the legacy `role`
column forever and are already covered by
`tests/test_authorization_and_guards.py` and `tests/test_user_management.py`.
"""

from sqlalchemy.orm import sessionmaker

from app.models import Role, User, UserRole
from app.services.authz import role_key


def _session(db_engine):
    return sessionmaker(bind=db_engine)()


def test_role_key_resolves_via_role_id_for_builtin_role(client, auth_headers, db_engine):
    resp = client.post(
        "/users",
        json={
            "email": "rolekey.manager@example.com",
            "full_name": "Role Key Manager",
            "password": "password123",
            "role": "manager",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    user_id = resp.json()["id"]

    db = _session(db_engine)
    try:
        user = db.get(User, user_id)
        assert user.role_id is not None
        assert role_key(user) == "manager"
    finally:
        db.close()


def test_role_key_falls_back_to_legacy_role_when_role_id_unset(db_engine):
    """Defensive fallback: a user constructed directly via the ORM (as
    several test fixtures across this suite do, e.g. `auth_headers`'s
    bootstrap admin), bypassing both `POST /users` and Round B1's migration
    backfill, never has `role_id` set. `role_key` must still resolve
    correctly off the legacy `role` column rather than crashing.
    """
    db = _session(db_engine)
    try:
        user = User(
            email="rolekey.fallback@example.com",
            full_name="Role Key Fallback",
            hashed_password="not-a-real-hash",
            role=UserRole.ADMIN,
            role_id=None,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        assert user.role_id is None
        assert role_key(user) == "admin"
    finally:
        db.close()


def test_update_user_role_resyncs_role_id_to_new_role(client, auth_headers, db_engine):
    """RBAC Round B2 point 3: `role` is currently the only API-facing field
    that ever changes which role a user holds, so `PATCH /users/{id}
    {"role": ...}` must keep `role_id` from going stale relative to it."""
    resp = client.post(
        "/users",
        json={
            "email": "resync@example.com",
            "full_name": "Resync Target",
            "password": "password123",
            "role": "employee",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    user_id = resp.json()["id"]

    db = _session(db_engine)
    try:
        user = db.get(User, user_id)
        employee_role_id = user.role_id
        assert employee_role_id is not None
        employee_role = db.get(Role, employee_role_id)
        assert employee_role.key == "employee"
    finally:
        db.close()

    resp = client.patch(f"/users/{user_id}", json={"role": "manager"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "manager"

    db = _session(db_engine)
    try:
        user = db.get(User, user_id)
        assert user.role_id is not None
        assert user.role_id != employee_role_id
        manager_role = db.get(Role, user.role_id)
        assert manager_role.key == "manager"
    finally:
        db.close()
