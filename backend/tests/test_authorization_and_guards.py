"""Ownership/role enforcement, the manager-scoped task list filter, and the
task-deletion safety guard — the GAPs flagged in
docs/design/kanban-timer-design.md §1.2 against the current backend.

`auth_headers` (see conftest.py) is the first-registered user, which
bootstraps to admin and owns/creates its own tasks by default, so these
tests always spin up additional employee/manager accounts explicitly to
exercise the non-admin paths.
"""


def _register(client, email, full_name="User"):
    client.post(
        "/auth/register",
        json={"email": email, "full_name": full_name, "password": "password123"},
    )
    token = client.post(
        "/auth/login", data={"username": email, "password": "password123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _make_task(client, headers, title="Task", **overrides):
    payload = {"title": title, "category": "meeting"}
    payload.update(overrides)
    return client.post("/tasks", json=payload, headers=headers).json()


# ---- Task read/write ownership (assignee, creator, admin; not just "authenticated") ----


def test_unrelated_employee_cannot_view_task(client, auth_headers):
    owner_headers = _register(client, "owner1@example.com")
    outsider_headers = _register(client, "outsider1@example.com")
    task = _make_task(client, owner_headers, "Owner's task")

    resp = client.get(f"/tasks/{task['id']}", headers=outsider_headers)
    assert resp.status_code == 403


def test_unrelated_employee_cannot_edit_or_delete_task(client, auth_headers):
    owner_headers = _register(client, "owner2@example.com")
    outsider_headers = _register(client, "outsider2@example.com")
    task = _make_task(client, owner_headers, "Owner's task")

    resp = client.patch(f"/tasks/{task['id']}", json={"title": "hacked"}, headers=outsider_headers)
    assert resp.status_code == 403

    resp = client.delete(f"/tasks/{task['id']}", headers=outsider_headers)
    assert resp.status_code == 403


def test_manager_can_view_but_not_edit_reports_task(client, auth_headers):
    manager_headers = _register(client, "manager1@example.com")
    manager = client.get("/users/me", headers=manager_headers).json()

    report_headers = _register(client, "report1@example.com")
    report_user = client.get("/users/me", headers=report_headers).json()
    client.patch(
        f"/users/{report_user['id']}", json={"manager_id": manager["id"]}, headers=auth_headers
    )

    task = _make_task(client, report_headers, "Report's task")

    resp = client.get(f"/tasks/{task['id']}", headers=manager_headers)
    assert resp.status_code == 200

    resp = client.patch(
        f"/tasks/{task['id']}", json={"title": "manager edit"}, headers=manager_headers
    )
    assert resp.status_code == 403

    resp = client.delete(f"/tasks/{task['id']}", headers=manager_headers)
    assert resp.status_code == 403


def test_admin_can_view_and_edit_any_task(client, auth_headers):
    owner_headers = _register(client, "owner3@example.com")
    task = _make_task(client, owner_headers, "Someone else's task")

    assert client.get(f"/tasks/{task['id']}", headers=auth_headers).status_code == 200
    resp = client.patch(f"/tasks/{task['id']}", json={"title": "admin edit"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["title"] == "admin edit"


def test_unrelated_employee_cannot_start_timer_on_others_task(client, auth_headers):
    owner_headers = _register(client, "owner4@example.com")
    outsider_headers = _register(client, "outsider4@example.com")
    task = _make_task(client, owner_headers, "Owner's task")
    client.patch(f"/tasks/{task['id']}", json={"status": "todo"}, headers=owner_headers)

    resp = client.post(f"/time-entries/start?task_id={task['id']}", headers=outsider_headers)
    assert resp.status_code == 403


def test_manager_cannot_start_pause_or_stop_reports_timer(client, auth_headers):
    manager_headers = _register(client, "manager2@example.com")
    manager = client.get("/users/me", headers=manager_headers).json()

    report_headers = _register(client, "report2@example.com")
    report_user = client.get("/users/me", headers=report_headers).json()
    client.patch(
        f"/users/{report_user['id']}", json={"manager_id": manager["id"]}, headers=auth_headers
    )

    task = _make_task(client, report_headers, "Report's task")
    client.patch(f"/tasks/{task['id']}", json={"status": "todo"}, headers=report_headers)

    resp = client.post(f"/time-entries/start?task_id={task['id']}", headers=manager_headers)
    assert resp.status_code == 403

    # The report starts it themselves; the manager still can't pause it.
    entry = client.post(
        f"/time-entries/start?task_id={task['id']}", headers=report_headers
    ).json()
    resp = client.post(f"/time-entries/{entry['id']}/pause", headers=manager_headers)
    assert resp.status_code == 404  # entry isn't owned by the manager


# ---- "My team" manager-scoped list filter ----


def test_list_tasks_manager_filter_returns_reports_tasks(client, auth_headers):
    manager_headers = _register(client, "manager3@example.com")
    manager = client.get("/users/me", headers=manager_headers).json()

    report_headers = _register(client, "report3@example.com")
    report_user = client.get("/users/me", headers=report_headers).json()
    client.patch(
        f"/users/{report_user['id']}", json={"manager_id": manager["id"]}, headers=auth_headers
    )

    _make_task(client, report_headers, "Report's task")

    resp = client.get(f"/tasks?manager_id={manager['id']}", headers=manager_headers)
    assert resp.status_code == 200
    titles = [t["title"] for t in resp.json()]
    assert "Report's task" in titles


def test_list_tasks_hides_unrelated_tasks_from_employees(client, auth_headers):
    owner_headers = _register(client, "owner5@example.com")
    outsider_headers = _register(client, "outsider5@example.com")
    _make_task(client, owner_headers, "Private task")

    resp = client.get("/tasks", headers=outsider_headers)
    assert resp.status_code == 200
    titles = [t["title"] for t in resp.json()]
    assert "Private task" not in titles


def test_list_tasks_admin_sees_everything(client, auth_headers):
    owner_headers = _register(client, "owner6@example.com")
    _make_task(client, owner_headers, "Someone's task")

    resp = client.get("/tasks", headers=auth_headers)
    assert resp.status_code == 200
    titles = [t["title"] for t in resp.json()]
    assert "Someone's task" in titles


# ---- Delete guard: a task with logged time can't be silently erased ----


def test_cannot_delete_task_with_time_entries(client, auth_headers, task_id):
    client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers)
    resp = client.delete(f"/tasks/{task_id}", headers=auth_headers)
    assert resp.status_code == 409

    # still there afterwards
    assert client.get(f"/tasks/{task_id}", headers=auth_headers).status_code == 200


def test_can_delete_task_without_time_entries(client, auth_headers, backlog_task_id):
    resp = client.delete(f"/tasks/{backlog_task_id}", headers=auth_headers)
    assert resp.status_code == 204
    assert client.get(f"/tasks/{backlog_task_id}", headers=auth_headers).status_code == 404
