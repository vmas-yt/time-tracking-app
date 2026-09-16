def _complete_task(client, auth_headers, title="Task"):
    task = client.post("/tasks", json={"title": title, "category": "meeting"}, headers=auth_headers).json()
    client.patch(f"/tasks/{task['id']}", json={"status": "todo"}, headers=auth_headers)
    entry = client.post(f"/time-entries/start?task_id={task['id']}", headers=auth_headers).json()
    client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)
    return task["id"]


def test_cycle_time_and_lead_time_report_completed_tasks(client, auth_headers):
    task_id = _complete_task(client, auth_headers)

    cycle = client.get("/reports/cycle-time", headers=auth_headers).json()
    assert any(p["task_id"] == task_id for p in cycle)

    lead = client.get("/reports/lead-time", headers=auth_headers).json()
    assert any(p["task_id"] == task_id for p in lead)


def test_throughput_counts_completed_tasks(client, auth_headers):
    _complete_task(client, auth_headers, "A")
    _complete_task(client, auth_headers, "B")

    buckets = client.get("/reports/throughput", headers=auth_headers).json()
    assert sum(b["completed_count"] for b in buckets) == 2


def test_cumulative_flow_reflects_current_statuses(client, auth_headers, backlog_task_id):
    cfd = client.get("/reports/cumulative-flow", headers=auth_headers).json()
    assert cfd, "expected at least one day of CFD data once a task exists"
    today = cfd[-1]
    assert today["counts"].get("backlog") == 1


def test_admin_can_configure_board_and_first_user_is_admin(client, auth_headers):
    me = client.get("/users/me", headers=auth_headers).json()
    assert me["role"] == "admin"

    resp = client.patch(
        "/admin/board-config", json={"swimlane_field": "task_type"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["swimlane_field"] == "task_type"


def test_non_admin_cannot_configure_board(client, auth_headers):
    client.post(
        "/auth/register",
        json={"email": "employee@example.com", "full_name": "Employee", "password": "password123"},
    )
    token = client.post(
        "/auth/login", data={"username": "employee@example.com", "password": "password123"}
    ).json()["access_token"]
    employee_headers = {"Authorization": f"Bearer {token}"}

    resp = client.patch(
        "/admin/board-config", json={"swimlane_field": "task_type"}, headers=employee_headers
    )
    assert resp.status_code == 403


def test_custom_field_lifecycle(client, auth_headers, task_id):
    field = client.post(
        "/admin/custom-fields",
        json={"name": "Ticket #", "field_type": "text"},
        headers=auth_headers,
    ).json()
    assert field["name"] == "Ticket #"

    updated = client.patch(
        f"/tasks/{task_id}",
        json={"custom_values": {field["id"]: "TT-123"}},
        headers=auth_headers,
    ).json()
    assert updated["custom_values"][field["id"]] == "TT-123"

    client.delete(f"/admin/custom-fields/{field['id']}", headers=auth_headers)
    fields = client.get("/admin/custom-fields", headers=auth_headers).json()
    assert fields == []


def test_reminder_candidates_flags_users_with_no_time_logged(client, auth_headers):
    resp = client.get("/notifications/reminders?days=1", headers=auth_headers)
    assert resp.status_code == 200
    candidates = resp.json()
    assert any(c["email"] == "dev@example.com" for c in candidates)
