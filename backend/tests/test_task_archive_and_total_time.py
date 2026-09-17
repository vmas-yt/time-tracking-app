"""Task archive/unarchive (§5.2) and TaskRead.total_logged_seconds (§7.2) —
per docs/design/custom-fields-admin-design.md.
"""

import time


def _login_headers(client, email, password="password123"):
    token = client.post("/auth/login", data={"username": email, "password": password}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def _create_employee(client, auth_headers, email):
    client.post(
        "/users",
        json={"email": email, "full_name": "User", "password": "password123", "role": "employee"},
        headers=auth_headers,
    )
    return _login_headers(client, email)


def _make_task(client, headers, title="Task", **overrides):
    payload = {"title": title, "category": "meeting"}
    payload.update(overrides)
    return client.post("/tasks", json=payload, headers=headers).json()


# ---- Archive / unarchive ----------------------------------------------------


def test_admin_can_archive_a_task(client, auth_headers, backlog_task_id):
    resp = client.post(f"/tasks/{backlog_task_id}/archive", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["archived_at"] is not None
    # Archiving is orthogonal to status — status is untouched.
    assert body["status"] == "backlog"


def test_archive_is_idempotent(client, auth_headers, backlog_task_id):
    first = client.post(f"/tasks/{backlog_task_id}/archive", headers=auth_headers).json()
    second = client.post(f"/tasks/{backlog_task_id}/archive", headers=auth_headers)
    assert second.status_code == 200
    assert second.json()["archived_at"] == first["archived_at"]


def test_archive_records_audit_entry(client, auth_headers, backlog_task_id):
    client.post(f"/tasks/{backlog_task_id}/archive", headers=auth_headers)
    audit = client.get(f"/tasks/{backlog_task_id}/audit", headers=auth_headers).json()
    assert any("archived" in a["detail"].lower() for a in audit)


def test_unarchive_clears_archived_at_and_is_idempotent(client, auth_headers, backlog_task_id):
    client.post(f"/tasks/{backlog_task_id}/archive", headers=auth_headers)
    resp = client.post(f"/tasks/{backlog_task_id}/unarchive", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is None

    # Idempotent — calling again on an already-unarchived task is fine.
    resp2 = client.post(f"/tasks/{backlog_task_id}/unarchive", headers=auth_headers)
    assert resp2.status_code == 200
    assert resp2.json()["archived_at"] is None


def test_non_admin_cannot_archive_own_task(client, auth_headers):
    employee_headers = _create_employee(client, auth_headers, "arch_emp1@example.com")
    task = _make_task(client, employee_headers, "Mine")
    resp = client.post(f"/tasks/{task['id']}/archive", headers=employee_headers)
    assert resp.status_code == 403


def test_archive_404_on_missing_task(client, auth_headers):
    resp = client.post("/tasks/does-not-exist/archive", headers=auth_headers)
    assert resp.status_code == 404


def test_archived_task_excluded_from_default_list(client, auth_headers, backlog_task_id):
    client.post(f"/tasks/{backlog_task_id}/archive", headers=auth_headers)
    resp = client.get("/tasks", headers=auth_headers)
    ids = [t["id"] for t in resp.json()]
    assert backlog_task_id not in ids


def test_include_archived_true_shows_archived_task_for_admin(client, auth_headers, backlog_task_id):
    client.post(f"/tasks/{backlog_task_id}/archive", headers=auth_headers)
    resp = client.get("/tasks?include_archived=true", headers=auth_headers)
    ids = [t["id"] for t in resp.json()]
    assert backlog_task_id in ids


def test_include_archived_ignored_for_non_admin(client, auth_headers):
    employee_headers = _create_employee(client, auth_headers, "arch_emp2@example.com")
    task = _make_task(client, employee_headers, "Employee task")
    client.post(f"/tasks/{task['id']}/archive", headers=auth_headers)

    resp = client.get("/tasks?include_archived=true", headers=employee_headers)
    ids = [t["id"] for t in resp.json()]
    assert task["id"] not in ids


def test_archived_task_still_directly_fetchable(client, auth_headers, backlog_task_id):
    client.post(f"/tasks/{backlog_task_id}/archive", headers=auth_headers)
    resp = client.get(f"/tasks/{backlog_task_id}", headers=auth_headers)
    assert resp.status_code == 200


def test_archived_completed_task_excluded_from_reports(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)

    cycle_before = client.get("/reports/cycle-time", headers=auth_headers).json()
    assert any(p["task_id"] == task_id for p in cycle_before)

    client.post(f"/tasks/{task_id}/archive", headers=auth_headers)

    cycle_after = client.get("/reports/cycle-time", headers=auth_headers).json()
    assert not any(p["task_id"] == task_id for p in cycle_after)

    lead_after = client.get("/reports/lead-time", headers=auth_headers).json()
    assert not any(p["task_id"] == task_id for p in lead_after)


# ---- total_logged_seconds (§7.2) -------------------------------------------


def test_total_logged_seconds_zero_for_fresh_task(client, auth_headers, backlog_task_id):
    task = client.get(f"/tasks/{backlog_task_id}", headers=auth_headers).json()
    assert task["total_logged_seconds"] == 0.0


def test_total_logged_seconds_reflects_stopped_entry(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    time.sleep(1.1)
    client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)

    task = client.get(f"/tasks/{task_id}", headers=auth_headers).json()
    assert task["total_logged_seconds"] >= 1.0


def test_total_logged_seconds_includes_live_running_segment(client, auth_headers, task_id):
    """Still-running case (§7.2's 'bonus' beyond the completed-task case)."""
    client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers)
    time.sleep(1.1)

    task = client.get(f"/tasks/{task_id}", headers=auth_headers).json()
    assert task["total_logged_seconds"] >= 1.0


def test_total_logged_seconds_visible_to_creator_not_just_assignee(client, auth_headers):
    """§7.4 — the fix this field exists for: a viewer who can see the task
    but isn't its timer's owner (here: creator assigns to someone else) still
    sees the total."""
    employee_headers = _create_employee(client, auth_headers, "time_emp1@example.com")
    employee = client.get("/users/me", headers=employee_headers).json()

    task = _make_task(client, auth_headers, "Assigned out", assignee_id=employee["id"])
    client.patch(f"/tasks/{task['id']}", json={"status": "todo"}, headers=auth_headers)
    entry = client.post(
        f"/time-entries/start?task_id={task['id']}", headers=employee_headers
    ).json()
    time.sleep(1.1)
    client.post(f"/time-entries/{entry['id']}/stop", headers=employee_headers)

    # Creator (admin here) can see the task and its total, despite not being
    # the entry's owner.
    seen = client.get(f"/tasks/{task['id']}", headers=auth_headers).json()
    assert seen["total_logged_seconds"] >= 1.0
