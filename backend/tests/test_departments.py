"""Departments: admin-gated mutations + has-active-teams delete guard —
mirrors tests/test_projects.py's conventions for the analogous Project CRUD
surface."""


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


def test_any_authenticated_user_can_list_departments(client, auth_headers):
    employee_headers = _create_employee(client, auth_headers, "dept_emp1@example.com")
    client.post("/departments", json={"name": "Engineering"}, headers=auth_headers)

    resp = client.get("/departments", headers=employee_headers)
    assert resp.status_code == 200
    assert any(d["name"] == "Engineering" for d in resp.json())


def test_non_admin_cannot_create_department(client, auth_headers):
    employee_headers = _create_employee(client, auth_headers, "dept_emp2@example.com")
    resp = client.post("/departments", json={"name": "Sales"}, headers=employee_headers)
    assert resp.status_code == 403


def test_admin_can_create_department(client, auth_headers):
    resp = client.post("/departments", json={"name": "Marketing"}, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Marketing"
    assert body["is_active"] is True


def test_create_department_duplicate_name_400(client, auth_headers):
    client.post("/departments", json={"name": "Finance"}, headers=auth_headers)
    resp = client.post("/departments", json={"name": "Finance"}, headers=auth_headers)
    assert resp.status_code == 400


def test_admin_can_patch_department_name(client, auth_headers):
    department = client.post("/departments", json={"name": "Ops"}, headers=auth_headers).json()

    resp = client.patch(
        f"/departments/{department['id']}", json={"name": "Operations"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Operations"


def test_non_admin_cannot_patch_department(client, auth_headers):
    employee_headers = _create_employee(client, auth_headers, "dept_emp3@example.com")
    department = client.post("/departments", json={"name": "Legal"}, headers=auth_headers).json()

    resp = client.patch(
        f"/departments/{department['id']}", json={"name": "Hacked"}, headers=employee_headers
    )
    assert resp.status_code == 403


def test_patch_nonexistent_department_404(client, auth_headers):
    resp = client.patch("/departments/does-not-exist", json={"name": "x"}, headers=auth_headers)
    assert resp.status_code == 404


def test_non_admin_cannot_delete_department(client, auth_headers):
    employee_headers = _create_employee(client, auth_headers, "dept_emp4@example.com")
    department = client.post("/departments", json={"name": "Support"}, headers=auth_headers).json()

    resp = client.delete(f"/departments/{department['id']}", headers=employee_headers)
    assert resp.status_code == 403


def test_admin_can_deactivate_department_without_active_teams(client, auth_headers):
    department = client.post("/departments", json={"name": "HR"}, headers=auth_headers).json()

    resp = client.delete(f"/departments/{department['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    # Row still exists (visible with include_inactive=true), just deactivated.
    listed = client.get("/departments?include_inactive=true", headers=auth_headers).json()
    assert any(d["id"] == department["id"] and not d["is_active"] for d in listed)


def test_admin_cannot_deactivate_department_with_active_team(client, auth_headers):
    department = client.post("/departments", json={"name": "Product"}, headers=auth_headers).json()
    client.post(
        "/teams",
        json={"name": "Growth", "department_id": department["id"]},
        headers=auth_headers,
    )

    resp = client.delete(f"/departments/{department['id']}", headers=auth_headers)
    assert resp.status_code == 409

    still_there = client.get("/departments?include_inactive=true", headers=auth_headers).json()
    assert any(d["id"] == department["id"] and d["is_active"] for d in still_there)


def test_admin_can_deactivate_department_after_deactivating_its_team(client, auth_headers):
    department = client.post("/departments", json={"name": "Design"}, headers=auth_headers).json()
    team = client.post(
        "/teams",
        json={"name": "UX", "department_id": department["id"]},
        headers=auth_headers,
    ).json()

    client.delete(f"/teams/{team['id']}", headers=auth_headers)

    resp = client.delete(f"/departments/{department['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_list_departments_excludes_inactive_by_default(client, auth_headers):
    department = client.post("/departments", json={"name": "Temp"}, headers=auth_headers).json()
    client.delete(f"/departments/{department['id']}", headers=auth_headers)

    listed = client.get("/departments", headers=auth_headers).json()
    assert not any(d["id"] == department["id"] for d in listed)


def test_list_departments_include_inactive_admin_only(client, auth_headers):
    department = client.post("/departments", json={"name": "Temp2"}, headers=auth_headers).json()
    client.delete(f"/departments/{department['id']}", headers=auth_headers)

    employee_headers = _create_employee(client, auth_headers, "dept_emp5@example.com")
    listed = client.get("/departments?include_inactive=true", headers=employee_headers).json()
    assert not any(d["id"] == department["id"] for d in listed)

    listed_admin = client.get("/departments?include_inactive=true", headers=auth_headers).json()
    assert any(d["id"] == department["id"] for d in listed_admin)
