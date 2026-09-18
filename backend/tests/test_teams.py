"""Teams: admin-gated mutations, has-active-member delete guard, the
unique-name-per-department constraint, and `services/teams.py::sync_team_manager`
actually being wired in from the two call sites this round adds it to
(`routers/teams.py` and `routers/users.py`)."""


def _login_headers(client, email, password="password123"):
    token = client.post("/auth/login", data={"username": email, "password": password}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def _create_employee(client, auth_headers, email, **overrides):
    payload = {"email": email, "full_name": "User", "password": "password123", "role": "employee"}
    payload.update(overrides)
    return client.post("/users", json=payload, headers=auth_headers).json()


def _create_manager(client, auth_headers, email, **overrides):
    payload = {"email": email, "full_name": "Manager", "password": "password123", "role": "manager"}
    payload.update(overrides)
    return client.post("/users", json=payload, headers=auth_headers).json()


def _create_department(client, auth_headers, name):
    return client.post("/departments", json={"name": name}, headers=auth_headers).json()


def _get_user(client, auth_headers, user_id):
    listed = client.get("/users?include_inactive=true", headers=auth_headers).json()
    return next(u for u in listed if u["id"] == user_id)


# ---- CRUD --------------------------------------------------------------------


def test_any_authenticated_user_can_list_teams(client, auth_headers):
    employee_headers = _login_headers(
        client, _create_employee(client, auth_headers, "team_emp1@example.com")["email"]
    )
    department = _create_department(client, auth_headers, "Engineering A")
    client.post("/teams", json={"name": "Backend", "department_id": department["id"]}, headers=auth_headers)

    resp = client.get("/teams", headers=employee_headers)
    assert resp.status_code == 200
    assert any(t["name"] == "Backend" for t in resp.json())


def test_non_admin_cannot_create_team(client, auth_headers):
    employee_headers = _login_headers(
        client, _create_employee(client, auth_headers, "team_emp2@example.com")["email"]
    )
    department = _create_department(client, auth_headers, "Engineering B")
    resp = client.post(
        "/teams", json={"name": "Frontend", "department_id": department["id"]}, headers=employee_headers
    )
    assert resp.status_code == 403


def test_admin_can_create_team(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering C")
    resp = client.post(
        "/teams", json={"name": "Platform", "department_id": department["id"]}, headers=auth_headers
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Platform"
    assert body["department_id"] == department["id"]
    assert body["manager_id"] is None
    assert body["is_active"] is True


def test_create_team_rejects_nonexistent_department_id(client, auth_headers):
    resp = client.post(
        "/teams", json={"name": "Orphan Team", "department_id": "does-not-exist"}, headers=auth_headers
    )
    assert resp.status_code == 400


def test_create_team_rejects_employee_as_manager(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering D")
    plain_employee = _create_employee(client, auth_headers, "team_emp3@example.com")

    resp = client.post(
        "/teams",
        json={"name": "QA", "department_id": department["id"], "manager_id": plain_employee["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "role 'manager' or 'admin'" in resp.json()["detail"]


def test_create_team_duplicate_name_in_same_department_400(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering E")
    client.post("/teams", json={"name": "Infra", "department_id": department["id"]}, headers=auth_headers)

    resp = client.post(
        "/teams", json={"name": "Infra", "department_id": department["id"]}, headers=auth_headers
    )
    assert resp.status_code == 400


def test_create_team_same_name_different_department_allowed(client, auth_headers):
    dept1 = _create_department(client, auth_headers, "Engineering F")
    dept2 = _create_department(client, auth_headers, "Engineering G")
    client.post("/teams", json={"name": "Core", "department_id": dept1["id"]}, headers=auth_headers)

    resp = client.post("/teams", json={"name": "Core", "department_id": dept2["id"]}, headers=auth_headers)
    assert resp.status_code == 201


def test_admin_can_patch_team_name_and_department(client, auth_headers):
    dept1 = _create_department(client, auth_headers, "Engineering H")
    dept2 = _create_department(client, auth_headers, "Engineering I")
    team = client.post(
        "/teams", json={"name": "Mobile", "department_id": dept1["id"]}, headers=auth_headers
    ).json()

    resp = client.patch(
        f"/teams/{team['id']}",
        json={"name": "Mobile Renamed", "department_id": dept2["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Mobile Renamed"
    assert body["department_id"] == dept2["id"]


def test_patch_team_rejects_nonexistent_department_id(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering J")
    team = client.post(
        "/teams", json={"name": "Data", "department_id": department["id"]}, headers=auth_headers
    ).json()

    resp = client.patch(
        f"/teams/{team['id']}", json={"department_id": "does-not-exist"}, headers=auth_headers
    )
    assert resp.status_code == 400


def test_patch_team_duplicate_name_within_department_400(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering K")
    client.post("/teams", json={"name": "Alpha Team", "department_id": department["id"]}, headers=auth_headers)
    beta = client.post(
        "/teams", json={"name": "Beta Team", "department_id": department["id"]}, headers=auth_headers
    ).json()

    resp = client.patch(f"/teams/{beta['id']}", json={"name": "Alpha Team"}, headers=auth_headers)
    assert resp.status_code == 400


def test_non_admin_cannot_patch_team(client, auth_headers):
    employee_headers = _login_headers(
        client, _create_employee(client, auth_headers, "team_emp4@example.com")["email"]
    )
    department = _create_department(client, auth_headers, "Engineering L")
    team = client.post(
        "/teams", json={"name": "Security", "department_id": department["id"]}, headers=auth_headers
    ).json()

    resp = client.patch(f"/teams/{team['id']}", json={"name": "Hacked"}, headers=employee_headers)
    assert resp.status_code == 403


def test_patch_nonexistent_team_404(client, auth_headers):
    resp = client.patch("/teams/does-not-exist", json={"name": "x"}, headers=auth_headers)
    assert resp.status_code == 404


def test_non_admin_cannot_delete_team(client, auth_headers):
    employee_headers = _login_headers(
        client, _create_employee(client, auth_headers, "team_emp5@example.com")["email"]
    )
    department = _create_department(client, auth_headers, "Engineering M")
    team = client.post(
        "/teams", json={"name": "Site Reliability", "department_id": department["id"]}, headers=auth_headers
    ).json()

    resp = client.delete(f"/teams/{team['id']}", headers=employee_headers)
    assert resp.status_code == 403


def test_admin_can_deactivate_team_without_active_members(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering N")
    team = client.post(
        "/teams", json={"name": "Empty Team", "department_id": department["id"]}, headers=auth_headers
    ).json()

    resp = client.delete(f"/teams/{team['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_admin_cannot_deactivate_team_with_active_member(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering O")
    team = client.post(
        "/teams", json={"name": "Staffed Team", "department_id": department["id"]}, headers=auth_headers
    ).json()
    _create_employee(client, auth_headers, "team_emp6@example.com", team_id=team["id"])

    resp = client.delete(f"/teams/{team['id']}", headers=auth_headers)
    assert resp.status_code == 409

    still_there = client.get("/teams?include_inactive=true", headers=auth_headers).json()
    assert any(t["id"] == team["id"] and t["is_active"] for t in still_there)


def test_admin_can_deactivate_team_after_member_deactivated(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering P")
    team = client.post(
        "/teams", json={"name": "Shrinking Team", "department_id": department["id"]}, headers=auth_headers
    ).json()
    member = _create_employee(client, auth_headers, "team_emp7@example.com", team_id=team["id"])

    client.delete(f"/users/{member['id']}", headers=auth_headers)

    resp = client.delete(f"/teams/{team['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_list_teams_filter_by_department_id(client, auth_headers):
    dept1 = _create_department(client, auth_headers, "Engineering Q")
    dept2 = _create_department(client, auth_headers, "Engineering R")
    team1 = client.post(
        "/teams", json={"name": "Team In Dept1", "department_id": dept1["id"]}, headers=auth_headers
    ).json()
    team2 = client.post(
        "/teams", json={"name": "Team In Dept2", "department_id": dept2["id"]}, headers=auth_headers
    ).json()

    resp = client.get(f"/teams?department_id={dept1['id']}", headers=auth_headers)
    ids = {t["id"] for t in resp.json()}
    assert team1["id"] in ids
    assert team2["id"] not in ids


def test_list_teams_excludes_inactive_by_default(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering S")
    team = client.post(
        "/teams", json={"name": "Soon Inactive", "department_id": department["id"]}, headers=auth_headers
    ).json()
    client.delete(f"/teams/{team['id']}", headers=auth_headers)

    listed = client.get("/teams", headers=auth_headers).json()
    assert not any(t["id"] == team["id"] for t in listed)


def test_list_teams_include_inactive_admin_only(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering T")
    team = client.post(
        "/teams", json={"name": "Hidden Team", "department_id": department["id"]}, headers=auth_headers
    ).json()
    client.delete(f"/teams/{team['id']}", headers=auth_headers)

    employee_headers = _login_headers(
        client, _create_employee(client, auth_headers, "team_emp8@example.com")["email"]
    )
    listed = client.get("/teams?include_inactive=true", headers=employee_headers).json()
    assert not any(t["id"] == team["id"] for t in listed)

    listed_admin = client.get("/teams?include_inactive=true", headers=auth_headers).json()
    assert any(t["id"] == team["id"] for t in listed_admin)


# ---- sync_team_manager wiring --------------------------------------------------


def test_create_team_with_manager_does_not_affect_unrelated_users_without_a_team(client, auth_headers):
    """Regression test: without a `db.flush()` between `db.add(team)` and
    `sync_team_manager(db, team)` in `create_team`, `team.id` is still
    `None` in Python at that point (SQLAlchemy's UUID `default=` callable
    is applied at flush time, not at object construction), so
    `sync_team_manager`'s `User.team_id == team.id` filter would compile to
    `team_id IS NULL` — mass-reassigning `manager_id` onto EVERY unplaced
    user in the system (including the new manager themselves, onto their
    own id) instead of just this brand-new, still-memberless team. Fails
    without the flush; passes with it."""
    department = _create_department(client, auth_headers, "Engineering Regression")
    unrelated_user = _create_employee(client, auth_headers, "regression_bystander@example.com")
    assert unrelated_user["team_id"] is None
    assert unrelated_user["manager_id"] is None

    manager = _create_manager(client, auth_headers, "regression_mgr@example.com")
    assert manager["team_id"] is None
    assert manager["manager_id"] is None

    resp = client.post(
        "/teams",
        json={"name": "Fresh Team", "department_id": department["id"], "manager_id": manager["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # The unrelated, still-unplaced user must be untouched.
    refreshed_bystander = _get_user(client, auth_headers, unrelated_user["id"])
    assert refreshed_bystander["manager_id"] is None

    # The new manager must not have been silently made their own manager.
    refreshed_manager = _get_user(client, auth_headers, manager["id"])
    assert refreshed_manager["manager_id"] is None

    # The bootstrap admin (also team_id None) must be untouched too.
    admin_me = client.get("/users/me", headers=auth_headers).json()
    assert admin_me["manager_id"] is None


def test_assigning_manager_to_team_updates_existing_members_manager_id(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering U")
    team = client.post(
        "/teams", json={"name": "Growing Team", "department_id": department["id"]}, headers=auth_headers
    ).json()
    manager = _create_manager(client, auth_headers, "team_mgr1@example.com")
    member = _create_employee(client, auth_headers, "team_member1@example.com", team_id=team["id"])
    assert _get_user(client, auth_headers, member["id"])["manager_id"] is None

    resp = client.patch(f"/teams/{team['id']}", json={"manager_id": manager["id"]}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["manager_id"] == manager["id"]

    refreshed_member = _get_user(client, auth_headers, member["id"])
    assert refreshed_member["manager_id"] == manager["id"]


def test_adding_member_to_team_with_existing_manager_picks_it_up_immediately(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering V")
    manager = _create_manager(client, auth_headers, "team_mgr2@example.com")
    team = client.post(
        "/teams",
        json={"name": "Managed Team", "department_id": department["id"], "manager_id": manager["id"]},
        headers=auth_headers,
    ).json()

    # New member created directly with team_id set (POST /users).
    new_member = _create_employee(client, auth_headers, "team_member2@example.com", team_id=team["id"])
    assert new_member["manager_id"] == manager["id"]

    # Existing member moved onto the team later (PATCH /users/{id}).
    unplaced = _create_employee(client, auth_headers, "team_member3@example.com")
    assert unplaced["manager_id"] is None
    resp = client.patch(f"/users/{unplaced['id']}", json={"team_id": team["id"]}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["manager_id"] == manager["id"]


def test_changing_team_manager_updates_all_members_not_stale(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering W")
    manager_a = _create_manager(client, auth_headers, "team_mgr3@example.com")
    manager_b = _create_manager(client, auth_headers, "team_mgr4@example.com")
    team = client.post(
        "/teams",
        json={"name": "Rotating Team", "department_id": department["id"], "manager_id": manager_a["id"]},
        headers=auth_headers,
    ).json()

    member1 = _create_employee(client, auth_headers, "team_member4@example.com", team_id=team["id"])
    member2 = _create_employee(client, auth_headers, "team_member5@example.com", team_id=team["id"])
    assert member1["manager_id"] == manager_a["id"]
    assert member2["manager_id"] == manager_a["id"]

    resp = client.patch(f"/teams/{team['id']}", json={"manager_id": manager_b["id"]}, headers=auth_headers)
    assert resp.status_code == 200

    refreshed1 = _get_user(client, auth_headers, member1["id"])
    refreshed2 = _get_user(client, auth_headers, member2["id"])
    assert refreshed1["manager_id"] == manager_b["id"]
    assert refreshed2["manager_id"] == manager_b["id"]


def test_clearing_team_manager_clears_members_manager_id(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering X")
    manager = _create_manager(client, auth_headers, "team_mgr5@example.com")
    team = client.post(
        "/teams",
        json={"name": "Deprecating Team", "department_id": department["id"], "manager_id": manager["id"]},
        headers=auth_headers,
    ).json()
    member = _create_employee(client, auth_headers, "team_member6@example.com", team_id=team["id"])
    assert member["manager_id"] == manager["id"]

    resp = client.patch(f"/teams/{team['id']}", json={"manager_id": None}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["manager_id"] is None

    refreshed = _get_user(client, auth_headers, member["id"])
    assert refreshed["manager_id"] is None


def test_detaching_user_from_team_clears_manager_id(client, auth_headers):
    """`manager_id` on a team member is a derived cache of the team's
    manager (sync_team_manager) — detaching the user (team_id -> null)
    without clearing it would leave that cache frozen at the old team's
    manager, so the detached user would keep showing up in that manager's
    reports/reminders indefinitely with no admin having actually chosen
    that. QA flagged this as a real gap during Round A verification."""
    department = _create_department(client, auth_headers, "Engineering Z")
    manager = _create_manager(client, auth_headers, "team_mgr7@example.com")
    team = client.post(
        "/teams",
        json={"name": "Detach Team", "department_id": department["id"], "manager_id": manager["id"]},
        headers=auth_headers,
    ).json()
    member = _create_employee(client, auth_headers, "team_member8@example.com", team_id=team["id"])
    assert member["manager_id"] == manager["id"]

    resp = client.patch(f"/users/{member['id']}", json={"team_id": None}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["team_id"] is None
    assert resp.json()["manager_id"] is None

    refreshed = _get_user(client, auth_headers, member["id"])
    assert refreshed["manager_id"] is None


def test_detaching_user_from_team_respects_explicit_manager_id_in_same_request(client, auth_headers):
    """A combined payload that both clears team_id AND explicitly sets a new
    manager_id in the same request should honor the explicit manager_id,
    not silently null it out."""
    department = _create_department(client, auth_headers, "Engineering Z2")
    old_manager = _create_manager(client, auth_headers, "team_mgr8@example.com")
    new_manager = _create_manager(client, auth_headers, "team_mgr9@example.com")
    team = client.post(
        "/teams",
        json={"name": "Detach Team 2", "department_id": department["id"], "manager_id": old_manager["id"]},
        headers=auth_headers,
    ).json()
    member = _create_employee(client, auth_headers, "team_member9@example.com", team_id=team["id"])
    assert member["manager_id"] == old_manager["id"]

    resp = client.patch(
        f"/users/{member['id']}",
        json={"team_id": None, "manager_id": new_manager["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["team_id"] is None
    assert resp.json()["manager_id"] == new_manager["id"]


def test_user_with_no_team_id_keeps_manager_id_directly_settable(client, auth_headers):
    manager = _create_manager(client, auth_headers, "team_mgr6@example.com")
    employee = _create_employee(client, auth_headers, "team_member7@example.com")
    assert employee["team_id"] is None

    resp = client.patch(
        f"/users/{employee['id']}", json={"manager_id": manager["id"]}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["manager_id"] == manager["id"]


def test_user_team_id_must_reference_existing_team(client, auth_headers):
    resp = client.post(
        "/users",
        json={
            "email": "team_bad1@example.com",
            "full_name": "User",
            "password": "password123",
            "role": "employee",
            "team_id": "does-not-exist",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_user_team_id_must_reference_active_team(client, auth_headers):
    department = _create_department(client, auth_headers, "Engineering Y")
    team = client.post(
        "/teams", json={"name": "Soon Gone", "department_id": department["id"]}, headers=auth_headers
    ).json()
    client.delete(f"/teams/{team['id']}", headers=auth_headers)

    resp = client.post(
        "/users",
        json={
            "email": "team_bad3@example.com",
            "full_name": "User",
            "password": "password123",
            "role": "employee",
            "team_id": team["id"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400
