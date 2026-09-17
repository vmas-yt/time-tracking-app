"""Role-based task-set scoping for reports endpoints — design doc §10.

Employee: own tasks only (assignee or creator). Manager: own + direct
reports' tasks. Admin: everything. Direct reports only, no recursive
hierarchy — same rule already used by `notifications.py::reminder_candidates`
and `GET /tasks`.
"""


def _create_user(client, auth_headers, email, role="employee", manager_id=None):
    payload = {"email": email, "full_name": "User", "password": "password123", "role": role}
    if manager_id is not None:
        payload["manager_id"] = manager_id
    return client.post("/users", json=payload, headers=auth_headers).json()


def _login_headers(client, email, password="password123"):
    token = client.post("/auth/login", data={"username": email, "password": password}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def _complete_task_for(client, headers, title="Task"):
    task = client.post(
        "/tasks", json={"title": title, "category": "meeting"}, headers=headers
    ).json()
    client.patch(f"/tasks/{task['id']}", json={"status": "todo"}, headers=headers)
    entry = client.post(f"/time-entries/start?task_id={task['id']}", headers=headers).json()
    client.post(f"/time-entries/{entry['id']}/stop", headers=headers)
    return task["id"]


def test_employee_only_sees_own_completed_tasks_in_reports(client, auth_headers):
    outsider = _create_user(client, auth_headers, "rep_outsider@example.com")
    outsider_headers = _login_headers(client, "rep_outsider@example.com")
    other_task_id = _complete_task_for(client, outsider_headers, "Outsider task")

    employee = _create_user(client, auth_headers, "rep_employee@example.com")
    employee_headers = _login_headers(client, "rep_employee@example.com")
    own_task_id = _complete_task_for(client, employee_headers, "Own task")

    cycle = client.get("/reports/cycle-time", headers=employee_headers).json()
    ids = {p["task_id"] for p in cycle}
    assert own_task_id in ids
    assert other_task_id not in ids


def test_manager_sees_own_and_direct_reports_completed_tasks(client, auth_headers):
    manager = _create_user(client, auth_headers, "rep_manager@example.com", role="manager")
    manager_headers = _login_headers(client, "rep_manager@example.com")

    report = _create_user(
        client, auth_headers, "rep_report@example.com", manager_id=manager["id"]
    )
    report_headers = _login_headers(client, "rep_report@example.com")

    outsider = _create_user(client, auth_headers, "rep_outsider2@example.com")
    outsider_headers = _login_headers(client, "rep_outsider2@example.com")

    manager_task_id = _complete_task_for(client, manager_headers, "Manager's own task")
    report_task_id = _complete_task_for(client, report_headers, "Report's task")
    outsider_task_id = _complete_task_for(client, outsider_headers, "Outsider's task")

    cycle = client.get("/reports/cycle-time", headers=manager_headers).json()
    ids = {p["task_id"] for p in cycle}
    assert manager_task_id in ids
    assert report_task_id in ids
    assert outsider_task_id not in ids


def test_admin_sees_all_completed_tasks_in_reports(client, auth_headers):
    employee = _create_user(client, auth_headers, "rep_emp2@example.com")
    employee_headers = _login_headers(client, "rep_emp2@example.com")
    task_id = _complete_task_for(client, employee_headers, "Someone's task")

    cycle = client.get("/reports/cycle-time", headers=auth_headers).json()
    ids = {p["task_id"] for p in cycle}
    assert task_id in ids


def test_throughput_and_lead_time_respect_scoping(client, auth_headers):
    outsider = _create_user(client, auth_headers, "rep_outsider3@example.com")
    outsider_headers = _login_headers(client, "rep_outsider3@example.com")
    _complete_task_for(client, outsider_headers, "Outsider throughput task")

    employee = _create_user(client, auth_headers, "rep_emp3@example.com")
    employee_headers = _login_headers(client, "rep_emp3@example.com")

    throughput = client.get("/reports/throughput", headers=employee_headers).json()
    assert sum(b["completed_count"] for b in throughput) == 0

    lead = client.get("/reports/lead-time", headers=employee_headers).json()
    assert lead == []


def test_cumulative_flow_respects_scoping(client, auth_headers):
    outsider = _create_user(client, auth_headers, "rep_outsider4@example.com")
    outsider_headers = _login_headers(client, "rep_outsider4@example.com")
    client.post(
        "/tasks", json={"title": "Outsider backlog task", "category": "meeting"}, headers=outsider_headers
    )

    employee = _create_user(client, auth_headers, "rep_emp4@example.com")
    employee_headers = _login_headers(client, "rep_emp4@example.com")
    client.post(
        "/tasks", json={"title": "Employee backlog task", "category": "meeting"}, headers=employee_headers
    )

    cfd = client.get("/reports/cumulative-flow", headers=employee_headers).json()
    assert cfd
    today = cfd[-1]
    # Only the employee's own task should be counted, not the outsider's.
    assert today["counts"].get("backlog") == 1
