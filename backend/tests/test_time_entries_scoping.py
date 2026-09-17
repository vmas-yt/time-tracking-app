"""`GET /time-entries?user_id=`/`?manager_id=` manager-review scoping —
design doc §11.
"""


def _login_headers(client, email, password="password123"):
    token = client.post("/auth/login", data={"username": email, "password": password}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def _create_user(client, auth_headers, email, role="employee", manager_id=None):
    payload = {"email": email, "full_name": "User", "password": "password123", "role": role}
    if manager_id is not None:
        payload["manager_id"] = manager_id
    return client.post("/users", json=payload, headers=auth_headers).json()


def _log_some_time(client, headers, title="Task"):
    task = client.post("/tasks", json={"title": title, "category": "meeting"}, headers=headers).json()
    client.patch(f"/tasks/{task['id']}", json={"status": "todo"}, headers=headers)
    entry = client.post(f"/time-entries/start?task_id={task['id']}", headers=headers).json()
    return entry["id"]


def test_no_params_returns_only_callers_own_entries(client, auth_headers):
    entry_id = _log_some_time(client, auth_headers)
    resp = client.get("/time-entries", headers=auth_headers)
    assert resp.status_code == 200
    assert [e["id"] for e in resp.json()] == [entry_id]


def test_user_id_param_self_allowed(client, auth_headers):
    employee = _create_user(client, auth_headers, "te_self@example.com")
    employee_headers = _login_headers(client, "te_self@example.com")
    entry_id = _log_some_time(client, employee_headers)

    resp = client.get(f"/time-entries?user_id={employee['id']}", headers=employee_headers)
    assert resp.status_code == 200
    assert [e["id"] for e in resp.json()] == [entry_id]


def test_user_id_param_forbidden_for_unrelated_employee(client, auth_headers):
    a = _create_user(client, auth_headers, "te_a@example.com")
    b = _create_user(client, auth_headers, "te_b@example.com")
    b_headers = _login_headers(client, "te_b@example.com")

    resp = client.get(f"/time-entries?user_id={a['id']}", headers=b_headers)
    assert resp.status_code == 403


def test_user_id_param_allowed_for_direct_manager(client, auth_headers):
    manager = _create_user(client, auth_headers, "te_mgr@example.com", role="manager")
    manager_headers = _login_headers(client, "te_mgr@example.com")
    report = _create_user(client, auth_headers, "te_report@example.com", manager_id=manager["id"])
    report_headers = _login_headers(client, "te_report@example.com")
    entry_id = _log_some_time(client, report_headers)

    resp = client.get(f"/time-entries?user_id={report['id']}", headers=manager_headers)
    assert resp.status_code == 200
    assert [e["id"] for e in resp.json()] == [entry_id]


def test_user_id_param_allowed_for_admin(client, auth_headers):
    employee = _create_user(client, auth_headers, "te_adminview@example.com")
    employee_headers = _login_headers(client, "te_adminview@example.com")
    entry_id = _log_some_time(client, employee_headers)

    resp = client.get(f"/time-entries?user_id={employee['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert [e["id"] for e in resp.json()] == [entry_id]


def test_manager_id_param_allowed_only_for_that_manager_or_admin(client, auth_headers):
    manager = _create_user(client, auth_headers, "te_mgr2@example.com", role="manager")
    manager_headers = _login_headers(client, "te_mgr2@example.com")
    report = _create_user(client, auth_headers, "te_report2@example.com", manager_id=manager["id"])
    report_headers = _login_headers(client, "te_report2@example.com")
    entry_id = _log_some_time(client, report_headers)

    other_manager = _create_user(client, auth_headers, "te_mgr3@example.com", role="manager")
    other_manager_headers = _login_headers(client, "te_mgr3@example.com")

    # Someone else's team is forbidden.
    resp = client.get(f"/time-entries?manager_id={manager['id']}", headers=other_manager_headers)
    assert resp.status_code == 403

    # The manager themself is allowed.
    resp = client.get(f"/time-entries?manager_id={manager['id']}", headers=manager_headers)
    assert resp.status_code == 200
    assert [e["id"] for e in resp.json()] == [entry_id]

    # Admin is allowed for any manager_id.
    resp = client.get(f"/time-entries?manager_id={manager['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert [e["id"] for e in resp.json()] == [entry_id]


def test_user_id_and_manager_id_mutually_exclusive(client, auth_headers):
    resp = client.get(
        "/time-entries?user_id=someone&manager_id=someone-else", headers=auth_headers
    )
    assert resp.status_code == 400
