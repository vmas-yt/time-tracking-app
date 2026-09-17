"""Projects: admin-gated mutations + has-tasks delete guard — design doc §12."""


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


def test_any_authenticated_user_can_list_and_get_projects(client, auth_headers):
    employee_headers = _create_employee(client, auth_headers, "proj_emp1@example.com")
    project = client.post(
        "/projects", json={"name": "Alpha"}, headers=auth_headers
    ).json()

    assert client.get("/projects", headers=employee_headers).status_code == 200
    assert client.get(f"/projects/{project['id']}", headers=employee_headers).status_code == 200


def test_non_admin_cannot_create_project(client, auth_headers):
    employee_headers = _create_employee(client, auth_headers, "proj_emp2@example.com")
    resp = client.post("/projects", json={"name": "Beta"}, headers=employee_headers)
    assert resp.status_code == 403


def test_admin_can_create_project(client, auth_headers):
    resp = client.post("/projects", json={"name": "Gamma"}, headers=auth_headers)
    assert resp.status_code == 201


def test_non_admin_cannot_delete_project(client, auth_headers):
    employee_headers = _create_employee(client, auth_headers, "proj_emp3@example.com")
    project = client.post("/projects", json={"name": "Delta"}, headers=auth_headers).json()

    resp = client.delete(f"/projects/{project['id']}", headers=employee_headers)
    assert resp.status_code == 403


def test_admin_can_delete_project_without_tasks(client, auth_headers):
    project = client.post("/projects", json={"name": "Epsilon"}, headers=auth_headers).json()
    resp = client.delete(f"/projects/{project['id']}", headers=auth_headers)
    assert resp.status_code == 204
    assert client.get(f"/projects/{project['id']}", headers=auth_headers).status_code == 404


def test_admin_cannot_delete_project_with_tasks(client, auth_headers):
    project = client.post("/projects", json={"name": "Zeta"}, headers=auth_headers).json()
    client.post(
        "/tasks",
        json={"title": "Linked task", "category": "meeting", "project_id": project["id"]},
        headers=auth_headers,
    )

    resp = client.delete(f"/projects/{project['id']}", headers=auth_headers)
    assert resp.status_code == 409

    # still there afterwards
    assert client.get(f"/projects/{project['id']}", headers=auth_headers).status_code == 200


# ---- project_id validation & PATCH wiring (§3.4) ---------------------------


def test_create_task_rejects_nonexistent_project_id(client, auth_headers):
    resp = client.post(
        "/tasks",
        json={"title": "Bad project", "category": "meeting", "project_id": "does-not-exist"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_patch_task_can_set_project_id(client, auth_headers, task_id):
    project = client.post("/projects", json={"name": "Eta"}, headers=auth_headers).json()
    resp = client.patch(f"/tasks/{task_id}", json={"project_id": project["id"]}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["project_id"] == project["id"]


def test_patch_task_rejects_nonexistent_project_id(client, auth_headers, task_id):
    resp = client.patch(
        f"/tasks/{task_id}", json={"project_id": "does-not-exist"}, headers=auth_headers
    )
    assert resp.status_code == 400


def test_patch_task_can_clear_project_id(client, auth_headers, task_id):
    project = client.post("/projects", json={"name": "Theta"}, headers=auth_headers).json()
    client.patch(f"/tasks/{task_id}", json={"project_id": project["id"]}, headers=auth_headers)

    resp = client.patch(f"/tasks/{task_id}", json={"project_id": None}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["project_id"] is None
