"""Admin user-management API and account deactivation — see
docs/design/auth-rbac-design.md §5, §6, §7.
"""


def _login(client, email, password="password123"):
    resp = client.post("/auth/login", data={"username": email, "password": password})
    return resp


def _login_headers(client, email, password="password123"):
    token = _login(client, email, password).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_user(client, auth_headers, email, role="employee", manager_id=None, password="password123", full_name="User"):
    payload = {"email": email, "full_name": full_name, "password": password, "role": role}
    if manager_id is not None:
        payload["manager_id"] = manager_id
    return client.post("/users", json=payload, headers=auth_headers)


# ---- POST /users -------------------------------------------------------------


def test_create_user_requires_admin(client, auth_headers):
    employee = _create_user(client, auth_headers, "e1@example.com").json()
    employee_headers = _login_headers(client, "e1@example.com")

    resp = _create_user(client, employee_headers, "e2@example.com")
    assert resp.status_code == 403


def test_create_user_success_defaults_to_employee_role(client, auth_headers):
    resp = client.post(
        "/users",
        json={"email": "new.hire@example.com", "full_name": "New Hire", "password": "password123"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "employee"
    assert body["is_active"] is True
    assert "hashed_password" not in body


def test_create_user_duplicate_email_400(client, auth_headers):
    _create_user(client, auth_headers, "dupe@example.com")
    resp = _create_user(client, auth_headers, "dupe@example.com")
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"]


def test_create_user_password_too_short_422(client, auth_headers):
    resp = _create_user(client, auth_headers, "short@example.com", password="short")
    assert resp.status_code == 422


def test_create_user_manager_id_must_exist(client, auth_headers):
    resp = _create_user(client, auth_headers, "orphan@example.com", manager_id="does-not-exist")
    assert resp.status_code == 400
    assert "does not reference an existing user" in resp.json()["detail"]


def test_create_user_manager_id_must_not_be_inactive(client, auth_headers):
    manager = _create_user(client, auth_headers, "mgr_inactive@example.com", role="manager").json()
    client.delete(f"/users/{manager['id']}", headers=auth_headers)

    resp = _create_user(client, auth_headers, "report_x@example.com", manager_id=manager["id"])
    assert resp.status_code == 400
    assert "deactivated" in resp.json()["detail"]


def test_create_user_manager_id_must_not_be_employee_role(client, auth_headers):
    plain_employee = _create_user(client, auth_headers, "plain@example.com").json()

    resp = _create_user(client, auth_headers, "report_y@example.com", manager_id=plain_employee["id"])
    assert resp.status_code == 400
    assert "role 'manager' or 'admin'" in resp.json()["detail"]


def test_create_user_manager_id_accepts_manager_or_admin_role(client, auth_headers):
    manager = _create_user(client, auth_headers, "mgr_ok@example.com", role="manager").json()
    resp = _create_user(client, auth_headers, "report_ok@example.com", manager_id=manager["id"])
    assert resp.status_code == 201

    admin_user = _create_user(client, auth_headers, "admin2@example.com", role="admin").json()
    resp = _create_user(client, auth_headers, "report_ok2@example.com", manager_id=admin_user["id"])
    assert resp.status_code == 201


# ---- PATCH /users/{id} --------------------------------------------------------


def test_non_admin_cannot_patch_users(client, auth_headers):
    employee = _create_user(client, auth_headers, "patch_target@example.com").json()
    employee_headers = _login_headers(client, "patch_target@example.com")

    resp = client.patch(
        f"/users/{employee['id']}", json={"full_name": "Hacked"}, headers=employee_headers
    )
    assert resp.status_code == 403


def test_patch_user_email_collision_400(client, auth_headers):
    _create_user(client, auth_headers, "taken@example.com")
    other = _create_user(client, auth_headers, "other@example.com").json()

    resp = client.patch(f"/users/{other['id']}", json={"email": "taken@example.com"}, headers=auth_headers)
    assert resp.status_code == 400


def test_patch_user_manager_id_self_reference_400(client, auth_headers):
    user = _create_user(client, auth_headers, "self_mgr@example.com", role="manager").json()
    resp = client.patch(f"/users/{user['id']}", json={"manager_id": user["id"]}, headers=auth_headers)
    assert resp.status_code == 400
    assert "own manager" in resp.json()["detail"]


def test_patch_user_updates_fields(client, auth_headers):
    user = _create_user(client, auth_headers, "editme@example.com").json()
    resp = client.patch(
        f"/users/{user['id']}",
        json={"full_name": "New Name", "role": "manager"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["full_name"] == "New Name"
    assert body["role"] == "manager"


# ---- DELETE /users/{id} (soft-delete/deactivate) -----------------------------


def test_delete_user_deactivates_not_removes(client, auth_headers):
    user = _create_user(client, auth_headers, "todelete@example.com").json()
    resp = client.delete(f"/users/{user['id']}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_active"] is False

    # Row still exists (visible with include_inactive=true).
    listed = client.get("/users?include_inactive=true", headers=auth_headers).json()
    assert any(u["id"] == user["id"] for u in listed)


def test_delete_user_requires_admin(client, auth_headers):
    a = _create_user(client, auth_headers, "victim@example.com").json()
    b_headers = _login_headers(client, "victim@example.com")
    other = _create_user(client, auth_headers, "other_victim@example.com").json()

    resp = client.delete(f"/users/{other['id']}", headers=b_headers)
    assert resp.status_code == 403


def test_delete_nonexistent_user_404(client, auth_headers):
    resp = client.delete("/users/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404


def test_cannot_deactivate_the_only_remaining_admin(client, auth_headers):
    """The only reachable way to hit `is_last_active_admin`'s guard through
    this API is for the sole active admin to try to deactivate themselves
    (any other admin calling this endpoint is themselves an active admin,
    so the count can never be 1 for a different target) — which is also
    exactly the new self-deactivation guard's scenario. That guard is
    checked first (see `deactivate_user`), so the sole admin gets the more
    specific "own account" reason rather than the "only remaining admin"
    one; both are 409s and the account is left untouched either way.
    """
    me = client.get("/users/me", headers=auth_headers).json()
    resp = client.delete(f"/users/{me['id']}", headers=auth_headers)
    assert resp.status_code == 409
    assert "own account" in resp.json()["detail"]


def test_admin_cannot_deactivate_own_account_via_delete(client, auth_headers):
    # A second active admin exists so this can't be conflated with the
    # only-remaining-admin guard — this must be rejected purely because the
    # actor is deactivating themselves.
    _create_user(client, auth_headers, "admin4@example.com", role="admin")

    me = client.get("/users/me", headers=auth_headers).json()
    resp = client.delete(f"/users/{me['id']}", headers=auth_headers)
    assert resp.status_code == 409
    assert "own account" in resp.json()["detail"]

    still_active = client.get("/users/me", headers=auth_headers).json()
    assert still_active["is_active"] is True


def test_admin_cannot_deactivate_own_account_via_patch(client, auth_headers):
    _create_user(client, auth_headers, "admin5@example.com", role="admin")

    me = client.get("/users/me", headers=auth_headers).json()
    resp = client.patch(f"/users/{me['id']}", json={"is_active": False}, headers=auth_headers)
    assert resp.status_code == 409
    assert "own account" in resp.json()["detail"]

    still_active = client.get("/users/me", headers=auth_headers).json()
    assert still_active["is_active"] is True


def test_admin_self_deactivate_combined_payload_does_not_apply_other_fields_first(
    client, auth_headers
):
    """A combined payload like {"role": "employee", "is_active": false} must
    be rejected before *any* field (e.g. role) is applied — mirroring the
    existing last-active-admin guard's ordering guarantee."""
    _create_user(client, auth_headers, "admin6@example.com", role="admin")

    me = client.get("/users/me", headers=auth_headers).json()
    assert me["role"] == "admin"

    resp = client.patch(
        f"/users/{me['id']}",
        json={"role": "employee", "is_active": False},
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert "own account" in resp.json()["detail"]

    refreshed = client.get("/users/me", headers=auth_headers).json()
    assert refreshed["role"] == "admin"
    assert refreshed["is_active"] is True


def test_can_deactivate_an_admin_when_another_active_admin_exists(client, auth_headers):
    second_admin = _create_user(client, auth_headers, "admin3@example.com", role="admin").json()
    resp = client.delete(f"/users/{second_admin['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_deactivating_user_auto_pauses_running_timer(client, auth_headers):
    employee = _create_user(client, auth_headers, "runner@example.com").json()
    employee_headers = _login_headers(client, "runner@example.com")

    task = client.post(
        "/tasks",
        json={"title": "Runner task", "category": "meeting", "assignee_id": employee["id"]},
        headers=auth_headers,
    ).json()
    client.patch(f"/tasks/{task['id']}", json={"status": "todo"}, headers=employee_headers)
    entry = client.post(
        f"/time-entries/start?task_id={task['id']}", headers=employee_headers
    ).json()
    assert entry["status"] == "running"

    resp = client.delete(f"/users/{employee['id']}", headers=auth_headers)
    assert resp.status_code == 200

    entries = client.get(
        f"/time-entries?user_id={employee['id']}", headers=auth_headers
    ).json()
    matching = [e for e in entries if e["id"] == entry["id"]]
    assert len(matching) == 1
    assert matching[0]["status"] == "paused"

    audit = client.get(f"/tasks/{task['id']}/audit", headers=auth_headers).json()
    details = [a["detail"] for a in audit]
    assert any("auto-paused" in d and "deactivated" in d for d in details)


def test_reactivate_user_via_patch(client, auth_headers):
    user = _create_user(client, auth_headers, "comeback@example.com").json()
    client.delete(f"/users/{user['id']}", headers=auth_headers)

    resp = client.patch(f"/users/{user['id']}", json={"is_active": True}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    # Reactivated user can log in again.
    login_resp = _login(client, "comeback@example.com")
    assert login_resp.status_code == 200


# ---- Login / get_current_user reject deactivated accounts --------------------


def test_deactivated_user_cannot_login(client, auth_headers):
    user = _create_user(client, auth_headers, "willbefired@example.com").json()
    client.delete(f"/users/{user['id']}", headers=auth_headers)

    resp = _login(client, "willbefired@example.com")
    assert resp.status_code == 403
    assert "deactivated" in resp.json()["detail"]


def test_deactivated_user_existing_token_rejected(client, auth_headers):
    user = _create_user(client, auth_headers, "tokenholder@example.com").json()
    headers = _login_headers(client, "tokenholder@example.com")

    # Token works before deactivation.
    assert client.get("/users/me", headers=headers).status_code == 200

    client.delete(f"/users/{user['id']}", headers=auth_headers)

    # Same still-unexpired token now fails, not at natural expiry.
    resp = client.get("/users/me", headers=headers)
    assert resp.status_code == 401


# ---- Passwords ----------------------------------------------------------------


def test_admin_reset_password_requires_admin(client, auth_headers):
    user = _create_user(client, auth_headers, "resetme@example.com").json()
    user_headers = _login_headers(client, "resetme@example.com")

    resp = client.post(
        f"/users/{user['id']}/reset-password", json={"new_password": "brandnewpass"}, headers=user_headers
    )
    assert resp.status_code == 403


def test_admin_reset_password_flow(client, auth_headers):
    user = _create_user(client, auth_headers, "resetme2@example.com").json()

    resp = client.post(
        f"/users/{user['id']}/reset-password", json={"new_password": "brandnewpass"}, headers=auth_headers
    )
    assert resp.status_code == 204

    assert _login(client, "resetme2@example.com", "brandnewpass").status_code == 200
    assert _login(client, "resetme2@example.com", "password123").status_code == 401


def test_admin_reset_password_too_short_422(client, auth_headers):
    user = _create_user(client, auth_headers, "resetme3@example.com").json()
    resp = client.post(
        f"/users/{user['id']}/reset-password", json={"new_password": "short"}, headers=auth_headers
    )
    assert resp.status_code == 422


def test_self_service_password_change_flow(client, auth_headers):
    user = _create_user(client, auth_headers, "selfchange@example.com").json()
    headers = _login_headers(client, "selfchange@example.com")

    resp = client.patch(
        "/users/me/password",
        json={"current_password": "password123", "new_password": "newpassword1"},
        headers=headers,
    )
    assert resp.status_code == 204

    assert _login(client, "selfchange@example.com", "newpassword1").status_code == 200
    assert _login(client, "selfchange@example.com", "password123").status_code == 401


def test_self_service_password_change_rejects_wrong_current_password(client, auth_headers):
    _create_user(client, auth_headers, "wrongcurrent@example.com")
    headers = _login_headers(client, "wrongcurrent@example.com")

    resp = client.patch(
        "/users/me/password",
        json={"current_password": "not-it", "new_password": "newpassword1"},
        headers=headers,
    )
    assert resp.status_code == 401


# ---- GET /users filtering ------------------------------------------------------


def test_list_users_excludes_inactive_by_default(client, auth_headers):
    user = _create_user(client, auth_headers, "hidden@example.com").json()
    client.delete(f"/users/{user['id']}", headers=auth_headers)

    listed = client.get("/users", headers=auth_headers).json()
    assert not any(u["id"] == user["id"] for u in listed)


def test_list_users_include_inactive_admin_only(client, auth_headers):
    user = _create_user(client, auth_headers, "hidden2@example.com").json()
    client.delete(f"/users/{user['id']}", headers=auth_headers)

    other = _create_user(client, auth_headers, "seer@example.com").json()
    other_headers = _login_headers(client, "seer@example.com")

    # Non-admin passing include_inactive=true has it silently ignored.
    listed = client.get("/users?include_inactive=true", headers=other_headers).json()
    assert not any(u["id"] == user["id"] for u in listed)

    listed_admin = client.get("/users?include_inactive=true", headers=auth_headers).json()
    assert any(u["id"] == user["id"] for u in listed_admin)


# ---- assignee_id must be an active user (§6.5) --------------------------------


def test_create_task_rejects_inactive_assignee(client, auth_headers):
    user = _create_user(client, auth_headers, "inactive_assignee@example.com").json()
    client.delete(f"/users/{user['id']}", headers=auth_headers)

    resp = client.post(
        "/tasks",
        json={"title": "Task", "category": "meeting", "assignee_id": user["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_patch_task_rejects_reassignment_to_inactive_user(client, auth_headers, task_id):
    user = _create_user(client, auth_headers, "inactive_assignee2@example.com").json()
    client.delete(f"/users/{user['id']}", headers=auth_headers)

    resp = client.patch(
        f"/tasks/{task_id}", json={"assignee_id": user["id"]}, headers=auth_headers
    )
    assert resp.status_code == 400
