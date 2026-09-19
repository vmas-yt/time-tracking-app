"""RBAC Round B3: custom roles + granular permissions + the permission-change
audit log — see docs/design/custom-roles-design.md.

Covers: the §1.4 escalation boundary (a permission-holding custom role gets
exactly the capability its permission grants, never more), role CRUD (§2.2-
§2.5), full-replacement permission assignment + the `manage_roles_permissions`/
`manage_users` non-membership rejection (§2.4/§1.1/§1.5), the audit log
(§2.4 Decision 2/§2.7), `resolve_role_assignment`'s resolution table (§4.2),
and the last-active-admin floor composing correctly with custom-role
assignment (§4.3).
"""


def _login_headers(client, email, password="password123"):
    token = client.post(
        "/auth/login", data={"username": email, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _register(client, auth_headers, email, full_name="User", role="employee", role_id=None):
    payload = {"email": email, "full_name": full_name, "password": "password123"}
    if role_id is not None:
        payload["role_id"] = role_id
    else:
        payload["role"] = role
    resp = client.post("/users", json=payload, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return _login_headers(client, email)


def _make_task(client, headers, title="Task", **overrides):
    payload = {"title": title, "category": "meeting"}
    payload.update(overrides)
    resp = client.post("/tasks", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_role(client, auth_headers, name):
    resp = client.post("/roles", json={"name": name}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_permissions(client, auth_headers, role_id, keys):
    return client.put(
        f"/roles/{role_id}/permissions", json={"permission_keys": keys}, headers=auth_headers
    )


def _builtin_role(client, auth_headers, key):
    roles = client.get("/roles", headers=auth_headers).json()
    return next(r for r in roles if r["key"] == key)


# ---- §1.4 escalation boundary: view_all_tasks -------------------------------


def test_view_all_tasks_only_role_can_view_but_not_edit_or_delete(client, auth_headers):
    role = _create_role(client, auth_headers, "Task Viewer")
    resp = _set_permissions(client, auth_headers, role["id"], ["view_all_tasks"])
    assert resp.status_code == 200
    assert resp.json()["permission_keys"] == ["view_all_tasks"]

    owner_headers = _register(client, auth_headers, "owner.viewperm@example.com")
    viewer_headers = _register(
        client, auth_headers, "viewer.viewperm@example.com", role_id=role["id"]
    )
    task = _make_task(client, owner_headers, "Owner's task")

    assert client.get(f"/tasks/{task['id']}", headers=viewer_headers).status_code == 200
    assert client.get(f"/tasks/{task['id']}/comments", headers=viewer_headers).status_code == 200
    resp = client.post(
        f"/tasks/{task['id']}/comments", json={"body": "hi"}, headers=viewer_headers
    )
    assert resp.status_code == 201
    assert client.get(f"/tasks/{task['id']}/audit", headers=viewer_headers).status_code == 200

    resp = client.patch(f"/tasks/{task['id']}", json={"title": "hacked"}, headers=viewer_headers)
    assert resp.status_code == 403
    resp = client.delete(f"/tasks/{task['id']}", headers=viewer_headers)
    assert resp.status_code == 403


def test_view_all_tasks_bypasses_list_ownership_filter(client, auth_headers):
    role = _create_role(client, auth_headers, "Task Viewer 2")
    _set_permissions(client, auth_headers, role["id"], ["view_all_tasks"])

    owner_headers = _register(client, auth_headers, "owner.listperm@example.com")
    viewer_headers = _register(
        client, auth_headers, "viewer.listperm@example.com", role_id=role["id"]
    )
    _make_task(client, owner_headers, "Someone else's task, list-visible")

    resp = client.get("/tasks", headers=viewer_headers)
    assert resp.status_code == 200
    titles = [t["title"] for t in resp.json()]
    assert "Someone else's task, list-visible" in titles


# ---- §1.4 escalation boundary: view_all_time_entries ------------------------


def test_view_all_time_entries_only_role_can_control_but_not_edit_task(client, auth_headers):
    role = _create_role(client, auth_headers, "Time Controller")
    _set_permissions(client, auth_headers, role["id"], ["view_all_time_entries"])

    owner_headers = _register(client, auth_headers, "owner.timeperm@example.com")
    controller_headers = _register(
        client, auth_headers, "controller.timeperm@example.com", role_id=role["id"]
    )
    task = _make_task(client, owner_headers, "Owner's timed task")
    client.patch(f"/tasks/{task['id']}", json={"status": "todo"}, headers=owner_headers)
    entry = client.post(
        f"/time-entries/start?task_id={task['id']}", headers=owner_headers
    ).json()

    # No task-edit rights leak from view_all_time_entries.
    resp = client.patch(
        f"/tasks/{task['id']}", json={"title": "hacked"}, headers=controller_headers
    )
    assert resp.status_code == 403
    resp = client.delete(f"/tasks/{task['id']}", headers=controller_headers)
    assert resp.status_code == 403

    # But full operational control over someone else's timer is granted.
    resp = client.post(f"/time-entries/{entry['id']}/pause", headers=controller_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"

    resp = client.post(f"/time-entries/{entry['id']}/resume", headers=controller_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"

    resp = client.post(f"/time-entries/{entry['id']}/stop", headers=controller_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_neither_permission_gets_404_on_others_entry_and_403_on_task(client, auth_headers):
    owner_headers = _register(client, auth_headers, "owner.noperm@example.com")
    outsider_headers = _register(client, auth_headers, "outsider.noperm@example.com")
    task = _make_task(client, owner_headers, "Owner's plain task")
    client.patch(f"/tasks/{task['id']}", json={"status": "todo"}, headers=owner_headers)
    entry = client.post(
        f"/time-entries/start?task_id={task['id']}", headers=owner_headers
    ).json()

    assert client.get(f"/tasks/{task['id']}", headers=outsider_headers).status_code == 403
    resp = client.post(f"/time-entries/{entry['id']}/pause", headers=outsider_headers)
    assert resp.status_code == 404


# ---- Role CRUD ---------------------------------------------------------------


def test_create_role_generates_unique_slug_key(client, auth_headers):
    role1 = _create_role(client, auth_headers, "Team Lead")
    assert role1["key"] == "team-lead"
    assert role1["is_builtin"] is False
    assert role1["permission_keys"] == []

    role2 = _create_role(client, auth_headers, "Team Lead")
    assert role2["key"] == "team-lead-2"

    role3 = _create_role(client, auth_headers, "Team Lead")
    assert role3["key"] == "team-lead-3"


def test_create_role_requires_admin(client, auth_headers):
    employee_headers = _register(client, auth_headers, "plain.rolecreate@example.com")
    resp = client.post("/roles", json={"name": "Nope"}, headers=employee_headers)
    assert resp.status_code == 403


def test_create_role_rejects_blank_name(client, auth_headers):
    resp = client.post("/roles", json={"name": "   "}, headers=auth_headers)
    assert resp.status_code == 400


def test_rename_custom_role(client, auth_headers):
    role = _create_role(client, auth_headers, "Old Name")
    resp = client.patch(f"/roles/{role['id']}", json={"name": "New Name"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New Name"
    assert body["key"] == role["key"]  # key is immutable


def test_builtin_role_cannot_be_renamed_permissioned_or_deleted(client, auth_headers):
    employee_role = _builtin_role(client, auth_headers, "employee")

    resp = client.patch(
        f"/roles/{employee_role['id']}", json={"name": "Renamed"}, headers=auth_headers
    )
    assert resp.status_code == 409

    resp = _set_permissions(client, auth_headers, employee_role["id"], ["manage_teams"])
    assert resp.status_code == 409

    resp = client.delete(f"/roles/{employee_role['id']}", headers=auth_headers)
    assert resp.status_code == 409


def test_builtin_role_audit_is_always_empty(client, auth_headers):
    admin_role = _builtin_role(client, auth_headers, "admin")
    resp = client.get(f"/roles/{admin_role['id']}/audit", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_delete_blocked_by_any_user_active_or_inactive(client, auth_headers):
    role = _create_role(client, auth_headers, "Occupied Role")
    user_resp = client.post(
        "/users",
        json={
            "email": "holder.occupied@example.com",
            "full_name": "Holder",
            "password": "password123",
            "role_id": role["id"],
        },
        headers=auth_headers,
    )
    assert user_resp.status_code == 201
    user_id = user_resp.json()["id"]

    resp = client.delete(f"/roles/{role['id']}", headers=auth_headers)
    assert resp.status_code == 409
    assert "Reassign them first" in resp.json()["detail"]

    # Deactivate the holder — still blocked (§6.3's active-or-inactive check).
    resp = client.patch(f"/users/{user_id}", json={"is_active": False}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    resp = client.delete(f"/roles/{role['id']}", headers=auth_headers)
    assert resp.status_code == 409
    assert "Reassign them first" in resp.json()["detail"]

    # Reassign off the role entirely — now deletable.
    resp = client.patch(f"/users/{user_id}", json={"role": "employee"}, headers=auth_headers)
    assert resp.status_code == 200

    resp = client.delete(f"/roles/{role['id']}", headers=auth_headers)
    assert resp.status_code == 204


def test_delete_blocked_once_role_has_audit_history(client, auth_headers):
    role = _create_role(client, auth_headers, "History Role")
    _set_permissions(client, auth_headers, role["id"], ["manage_teams"])

    # Never assigned to anyone, but has permission-change history now.
    resp = client.delete(f"/roles/{role['id']}", headers=auth_headers)
    assert resp.status_code == 409
    assert "audit trail" in resp.json()["detail"]

    # Emptying the permission set doesn't erase the history rows already
    # written — still undeletable, permanently, per the design's own
    # "once changed, never deletable again" trade-off.
    _set_permissions(client, auth_headers, role["id"], [])
    resp = client.delete(f"/roles/{role['id']}", headers=auth_headers)
    assert resp.status_code == 409


def test_role_never_touched_stays_freely_deletable(client, auth_headers):
    role = _create_role(client, auth_headers, "Mis-clicked Role")
    resp = client.delete(f"/roles/{role['id']}", headers=auth_headers)
    assert resp.status_code == 204


def test_delete_role_requires_admin(client, auth_headers):
    role = _create_role(client, auth_headers, "Protected Role")
    employee_headers = _register(client, auth_headers, "plain.roledelete@example.com")
    resp = client.delete(f"/roles/{role['id']}", headers=employee_headers)
    assert resp.status_code == 403


# ---- Permission assignment ----------------------------------------------------


def test_put_permissions_full_replacement_semantics(client, auth_headers):
    role = _create_role(client, auth_headers, "Replacement Role")
    resp = _set_permissions(client, auth_headers, role["id"], ["manage_teams", "view_all_tasks"])
    assert sorted(resp.json()["permission_keys"]) == ["manage_teams", "view_all_tasks"]

    resp = _set_permissions(client, auth_headers, role["id"], ["archive_tasks"])
    assert resp.json()["permission_keys"] == ["archive_tasks"]  # old set fully replaced, not merged


def test_put_permissions_rejects_manage_roles_permissions_and_manage_users(client, auth_headers):
    role = _create_role(client, auth_headers, "Bad Perms Role")
    resp = _set_permissions(client, auth_headers, role["id"], ["manage_roles_permissions"])
    assert resp.status_code == 422

    resp = _set_permissions(client, auth_headers, role["id"], ["manage_users"])
    assert resp.status_code == 422


def test_put_permissions_requires_admin(client, auth_headers):
    role = _create_role(client, auth_headers, "Guarded Perms Role")
    employee_headers = _register(client, auth_headers, "plain.permsput@example.com")
    resp = _set_permissions(client, employee_headers, role["id"], ["manage_teams"])
    assert resp.status_code == 403


# ---- Audit log ----------------------------------------------------------------


def test_audit_log_records_diff_per_batch_and_orders_newest_first(client, auth_headers):
    role = _create_role(client, auth_headers, "Audited Role")

    resp1 = _set_permissions(client, auth_headers, role["id"], ["manage_teams", "view_all_tasks"])
    assert resp1.status_code == 200

    resp2 = _set_permissions(client, auth_headers, role["id"], ["manage_projects", "view_all_tasks"])
    assert resp2.status_code == 200

    audit = client.get(f"/roles/{role['id']}/audit", headers=auth_headers)
    assert audit.status_code == 200
    entries = audit.json()
    assert len(entries) == 2  # one batch per PUT call

    # Newest first: the second call (manage_teams -> manage_projects swap).
    newest, oldest = entries
    assert sorted(newest["added"]) == ["manage_projects"]
    assert sorted(newest["removed"]) == ["manage_teams"]
    assert sorted(oldest["added"]) == ["manage_teams", "view_all_tasks"]
    assert oldest["removed"] == []
    assert newest["batch_id"] != oldest["batch_id"]
    assert newest["actor"]["email"] == "dev@example.com"


def test_audit_log_no_op_resubmit_writes_nothing(client, auth_headers):
    role = _create_role(client, auth_headers, "No-op Role")
    _set_permissions(client, auth_headers, role["id"], ["manage_teams"])
    _set_permissions(client, auth_headers, role["id"], ["manage_teams"])  # identical set again

    entries = client.get(f"/roles/{role['id']}/audit", headers=auth_headers).json()
    assert len(entries) == 1


def test_get_role_audit_requires_admin(client, auth_headers):
    role = _create_role(client, auth_headers, "Audit Guard Role")
    _set_permissions(client, auth_headers, role["id"], ["manage_teams"])
    employee_headers = _register(client, auth_headers, "plain.auditget@example.com")
    resp = client.get(f"/roles/{role['id']}/audit", headers=employee_headers)
    assert resp.status_code == 403


# ---- resolve_role_assignment (§4.2) -------------------------------------------


def test_create_user_with_no_role_fields_defaults_to_employee(client, auth_headers):
    resp = client.post(
        "/users",
        json={"email": "neither.given@example.com", "full_name": "Neither", "password": "password123"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "employee"
    employee_role = _builtin_role(client, auth_headers, "employee")
    assert body["role_id"] == employee_role["id"]
    assert body["role_name"] == "Employee"


def test_create_user_with_role_field_resolves_role_id(client, auth_headers):
    resp = client.post(
        "/users",
        json={
            "email": "role.given@example.com",
            "full_name": "Role Given",
            "password": "password123",
            "role": "manager",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    manager_role = _builtin_role(client, auth_headers, "manager")
    assert body["role_id"] == manager_role["id"]
    assert body["role_name"] == "Manager"


def test_create_user_with_builtin_role_id_resolves_role_field(client, auth_headers):
    manager_role = _builtin_role(client, auth_headers, "manager")
    resp = client.post(
        "/users",
        json={
            "email": "roleid.builtin@example.com",
            "full_name": "Role Id Builtin",
            "password": "password123",
            "role_id": manager_role["id"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "manager"
    assert body["role_id"] == manager_role["id"]


def test_create_user_with_custom_role_id_leaves_role_null(client, auth_headers):
    role = _create_role(client, auth_headers, "Custom Assignee Role")
    resp = client.post(
        "/users",
        json={
            "email": "roleid.custom@example.com",
            "full_name": "Role Id Custom",
            "password": "password123",
            "role_id": role["id"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] is None  # §4.4's fix: this must not 500
    assert body["role_id"] == role["id"]
    assert body["role_name"] == role["name"]

    # Also verify GET /users/{id} and GET /users/me-equivalents don't crash
    # serializing a user with role == NULL.
    login = _login_headers(client, "roleid.custom@example.com")
    resp = client.get("/users/me", headers=login)
    assert resp.status_code == 200
    assert resp.json()["role"] is None


def test_create_user_with_nonexistent_role_id_400(client, auth_headers):
    resp = client.post(
        "/users",
        json={
            "email": "roleid.bad@example.com",
            "full_name": "Bad Role Id",
            "password": "password123",
            "role_id": "not-a-real-id",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_create_user_with_both_role_and_role_id_400(client, auth_headers):
    manager_role = _builtin_role(client, auth_headers, "manager")
    resp = client.post(
        "/users",
        json={
            "email": "roleid.both@example.com",
            "full_name": "Both",
            "password": "password123",
            "role": "employee",
            "role_id": manager_role["id"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_update_user_role_id_to_custom_role(client, auth_headers):
    headers = _register(client, auth_headers, "patchable.custom@example.com")
    me = client.get("/users/me", headers=headers).json()

    role = _create_role(client, auth_headers, "Patched Custom Role")
    resp = client.patch(f"/users/{me['id']}", json={"role_id": role["id"]}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] is None
    assert body["role_id"] == role["id"]
    assert body["role_name"] == role["name"]


def test_update_user_explicit_null_role_id_nulls_out_symmetrically_with_null_role(client, auth_headers):
    """An explicit `{"role_id": null}` (no `role` field) must null out both
    columns exactly like the pre-existing `{"role": null}` path already
    does -- not silently fall through to `resolve_role_assignment`'s
    "neither given" branch (create-only, defaults to Employee) and promote
    the user to Employee instead. Regression for a real asymmetry found in
    review: the two null-out spellings should be equivalent."""
    headers = _register(client, auth_headers, "null-role-id@example.com")
    me = client.get("/users/me", headers=headers).json()
    assert me["role"] == "employee"

    resp = client.patch(f"/users/{me['id']}", json={"role_id": None}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] is None
    assert body["role_id"] is None


# ---- Last-active-admin floor composes with custom-role assignment (§4.3) ------


def test_cannot_assign_custom_role_to_sole_active_admin(client, auth_headers):
    me = client.get("/users/me", headers=auth_headers).json()
    role = _create_role(client, auth_headers, "Admin Replacement Role")

    resp = client.patch(f"/users/{me['id']}", json={"role_id": role["id"]}, headers=auth_headers)
    assert resp.status_code == 409
    assert "only remaining admin" in resp.json()["detail"]

    still_admin = client.get("/users/me", headers=auth_headers).json()
    assert still_admin["role"] == "admin"


def test_can_assign_custom_role_to_admin_when_another_admin_remains(client, auth_headers):
    second_admin_headers = _register(
        client, auth_headers, "second.admin.customrole@example.com", role="admin"
    )
    me = client.get("/users/me", headers=auth_headers).json()
    role = _create_role(client, auth_headers, "Safe Replacement Role")

    resp = client.patch(f"/users/{me['id']}", json={"role_id": role["id"]}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] is None

    # Restore, so this test doesn't leave a dangling deactivate-prevention
    # surprise for any test ordering assumptions elsewhere.
    client.patch(f"/users/{me['id']}", json={"role": "admin"}, headers=second_admin_headers)
