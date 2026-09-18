"""Task.team_id: the one-time default-at-creation logic (assignee's team,
else creator's team, else null — see the comment on Task.team_id in
models.py) plus the explicit-override / later-PATCH-move paths."""


def _create_department(client, auth_headers, name):
    return client.post("/departments", json={"name": name}, headers=auth_headers).json()


def _create_team(client, auth_headers, department_id, name):
    return client.post(
        "/teams", json={"name": name, "department_id": department_id}, headers=auth_headers
    ).json()


def _create_employee(client, auth_headers, email, **overrides):
    payload = {"email": email, "full_name": "User", "password": "password123", "role": "employee"}
    payload.update(overrides)
    return client.post("/users", json=payload, headers=auth_headers).json()


def test_task_inherits_assignees_team_when_assignee_given(client, auth_headers):
    department = _create_department(client, auth_headers, "Task Dept A")
    team = _create_team(client, auth_headers, department["id"], "Team A")
    assignee = _create_employee(client, auth_headers, "task_team_emp1@example.com", team_id=team["id"])

    resp = client.post(
        "/tasks",
        json={"title": "Assigned task", "category": "meeting", "assignee_id": assignee["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["team_id"] == team["id"]


def test_task_inherits_creators_team_when_no_assignee_given(client, auth_headers):
    department = _create_department(client, auth_headers, "Task Dept B")
    team = _create_team(client, auth_headers, department["id"], "Team B")

    creator_headers_user = _create_employee(
        client, auth_headers, "task_team_creator1@example.com", team_id=team["id"], role="manager"
    )
    login = client.post(
        "/auth/login", data={"username": "task_team_creator1@example.com", "password": "password123"}
    ).json()
    creator_headers = {"Authorization": f"Bearer {login['access_token']}"}

    resp = client.post(
        "/tasks", json={"title": "Self-assigned task", "category": "meeting"}, headers=creator_headers
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["assignee_id"] == creator_headers_user["id"]
    assert body["team_id"] == team["id"]


def test_task_team_id_is_null_when_neither_assignee_nor_creator_has_a_team(client, auth_headers):
    # `auth_headers`'s bootstrap admin has no team_id (never assigned one).
    resp = client.post(
        "/tasks", json={"title": "Homeless task", "category": "meeting"}, headers=auth_headers
    )
    assert resp.status_code == 201
    assert resp.json()["team_id"] is None


def test_explicit_team_id_in_create_payload_overrides_defaults(client, auth_headers):
    department = _create_department(client, auth_headers, "Task Dept C")
    assignee_team = _create_team(client, auth_headers, department["id"], "Assignee Team")
    override_team = _create_team(client, auth_headers, department["id"], "Override Team")
    assignee = _create_employee(
        client, auth_headers, "task_team_emp2@example.com", team_id=assignee_team["id"]
    )

    resp = client.post(
        "/tasks",
        json={
            "title": "Overridden task",
            "category": "meeting",
            "assignee_id": assignee["id"],
            "team_id": override_team["id"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["team_id"] == override_team["id"]


def test_create_task_rejects_nonexistent_team_id(client, auth_headers):
    resp = client.post(
        "/tasks",
        json={"title": "Bad team task", "category": "meeting", "team_id": "does-not-exist"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_patch_can_move_task_to_a_different_team_explicitly(client, auth_headers, task_id):
    department = _create_department(client, auth_headers, "Task Dept D")
    team = _create_team(client, auth_headers, department["id"], "Destination Team")

    resp = client.patch(f"/tasks/{task_id}", json={"team_id": team["id"]}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["team_id"] == team["id"]

    # Can also be cleared back to null explicitly.
    resp2 = client.patch(f"/tasks/{task_id}", json={"team_id": None}, headers=auth_headers)
    assert resp2.status_code == 200
    assert resp2.json()["team_id"] is None


def test_patch_task_rejects_nonexistent_team_id(client, auth_headers, task_id):
    resp = client.patch(f"/tasks/{task_id}", json={"team_id": "does-not-exist"}, headers=auth_headers)
    assert resp.status_code == 400


def test_task_team_id_not_re_derived_after_creation(client, auth_headers):
    """One-time default at creation, not a live derivation: if the assignee
    later moves to a different team, the task's own team_id stays put."""
    department = _create_department(client, auth_headers, "Task Dept E")
    original_team = _create_team(client, auth_headers, department["id"], "Original Team")
    new_team = _create_team(client, auth_headers, department["id"], "New Team")
    assignee = _create_employee(
        client, auth_headers, "task_team_emp3@example.com", team_id=original_team["id"]
    )

    task = client.post(
        "/tasks",
        json={"title": "Sticky team task", "category": "meeting", "assignee_id": assignee["id"]},
        headers=auth_headers,
    ).json()
    assert task["team_id"] == original_team["id"]

    client.patch(f"/users/{assignee['id']}", json={"team_id": new_team["id"]}, headers=auth_headers)

    refreshed_task = client.get(f"/tasks/{task['id']}", headers=auth_headers).json()
    assert refreshed_task["team_id"] == original_team["id"]
