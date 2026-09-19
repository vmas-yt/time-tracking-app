"""Round C (team-scoped boards, per-team swim lanes, board renaming) — see
docs/design/team-scoped-boards-design.md.

Covers:
  * §5.1 escalation boundary — same-team view access, fully effective
    (task detail, comments, audit trail) but strictly view-only (no
    edit/delete, no timer control).
  * §5.1.1's `task.team_id is not None` guard — two team-less users must not
    see each other's team-less tasks through the new branch.
  * A different-team user with no other relationship stays excluded/403.
  * `GET /tasks?team_id=` narrows but never widens the existing visibility
    floor.
  * `GET`/`PATCH /teams/{id}/board-config` — lazy-create defaults, rename,
    swim-lane change, per-team independence (including independence from
    the global `board_config` singleton), admin-only gating (explicitly
    including that team's own manager getting 403), and `can_manage`
    accuracy on both endpoints for a permission holder vs. a plain
    employee.
"""


def _create_department(client, auth_headers, name):
    resp = client.post("/departments", json={"name": name}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_team(client, auth_headers, department_id, name):
    resp = client.post(
        "/teams", json={"name": name, "department_id": department_id}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login_headers(client, email, password="password123"):
    token = client.post(
        "/auth/login", data={"username": email, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_user(client, auth_headers, email, **overrides):
    payload = {"email": email, "full_name": "User", "password": "password123"}
    if "role_id" not in overrides:
        payload["role"] = overrides.pop("role", "employee")
    payload.update(overrides)
    resp = client.post("/users", json=payload, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _register_and_login(client, auth_headers, email, **overrides):
    _create_user(client, auth_headers, email, **overrides)
    return _login_headers(client, email)


def _make_task(client, headers, title="Task", **overrides):
    payload = {"title": title, "category": "meeting"}
    payload.update(overrides)
    resp = client.post("/tasks", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_role(client, auth_headers, name):
    resp = client.post("/roles", json={"name": name}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_permissions(client, auth_headers, role_id, keys):
    resp = client.put(
        f"/roles/{role_id}/permissions", json={"permission_keys": keys}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    return resp


# ---- §5.1 escalation boundary: same-team view access ------------------------


def test_same_team_user_can_view_task_comments_and_audit_but_not_edit_or_control_timer(
    client, auth_headers
):
    dept = _create_department(client, auth_headers, "Dept A")
    team = _create_team(client, auth_headers, dept["id"], "Team A")

    owner_headers = _register_and_login(
        client, auth_headers, "owner.sameteam@example.com", team_id=team["id"]
    )
    teammate_headers = _register_and_login(
        client, auth_headers, "teammate.sameteam@example.com", team_id=team["id"]
    )

    task = _make_task(client, owner_headers, "Owner's task")
    assert task["team_id"] == team["id"]

    # View, fully effective: detail, comments, audit.
    resp = client.get(f"/tasks/{task['id']}", headers=teammate_headers)
    assert resp.status_code == 200

    resp = client.get(f"/tasks/{task['id']}/comments", headers=teammate_headers)
    assert resp.status_code == 200

    resp = client.post(
        f"/tasks/{task['id']}/comments", json={"body": "hi teammate"}, headers=teammate_headers
    )
    assert resp.status_code == 201

    resp = client.get(f"/tasks/{task['id']}/audit", headers=teammate_headers)
    assert resp.status_code == 200

    # View only: no edit/delete.
    resp = client.patch(f"/tasks/{task['id']}", json={"title": "hacked"}, headers=teammate_headers)
    assert resp.status_code == 403

    resp = client.delete(f"/tasks/{task['id']}", headers=teammate_headers)
    assert resp.status_code == 403

    # Also appears on the team-filtered list.
    resp = client.get(f"/tasks?team_id={team['id']}", headers=teammate_headers)
    assert resp.status_code == 200
    assert task["id"] in [t["id"] for t in resp.json()]


def test_same_team_user_cannot_control_timer_on_teammates_task(client, auth_headers):
    dept = _create_department(client, auth_headers, "Dept A2")
    team = _create_team(client, auth_headers, dept["id"], "Team A2")

    owner_headers = _register_and_login(
        client, auth_headers, "owner.timer@example.com", team_id=team["id"]
    )
    teammate_headers = _register_and_login(
        client, auth_headers, "teammate.timer@example.com", team_id=team["id"]
    )

    task = _make_task(client, owner_headers, "Owner's timer task")
    client.patch(f"/tasks/{task['id']}", json={"status": "todo"}, headers=owner_headers)

    resp = client.post(f"/time-entries/start?task_id={task['id']}", headers=owner_headers)
    assert resp.status_code == 201
    entry = resp.json()

    # Teammate cannot pause/resume/stop the owner's timer.
    assert client.post(f"/time-entries/{entry['id']}/pause", headers=teammate_headers).status_code in (
        403,
        404,
    )
    assert client.post(f"/time-entries/{entry['id']}/resume", headers=teammate_headers).status_code in (
        403,
        404,
    )
    assert client.post(f"/time-entries/{entry['id']}/stop", headers=teammate_headers).status_code in (
        403,
        404,
    )

    # Owner can still stop it themself.
    assert client.post(f"/time-entries/{entry['id']}/stop", headers=owner_headers).status_code == 200


# ---- §5.1.1 guard: team-less users must not see each other's team-less tasks


def test_team_less_users_do_not_see_each_others_team_less_tasks(client, auth_headers):
    owner_headers = _register_and_login(client, auth_headers, "owner.noteam@example.com")
    other_headers = _register_and_login(client, auth_headers, "other.noteam@example.com")

    task = _make_task(client, owner_headers, "Homeless task")
    assert task["team_id"] is None

    resp = client.get(f"/tasks/{task['id']}", headers=other_headers)
    assert resp.status_code == 403

    resp = client.get("/tasks", headers=other_headers)
    assert resp.status_code == 200
    assert task["id"] not in [t["id"] for t in resp.json()]


# ---- Different-team user: unchanged 403/exclusion ---------------------------


def test_different_team_user_still_excluded(client, auth_headers):
    dept = _create_department(client, auth_headers, "Dept B")
    team1 = _create_team(client, auth_headers, dept["id"], "Team B1")
    team2 = _create_team(client, auth_headers, dept["id"], "Team B2")

    owner_headers = _register_and_login(
        client, auth_headers, "owner.diffteam@example.com", team_id=team1["id"]
    )
    other_headers = _register_and_login(
        client, auth_headers, "other.diffteam@example.com", team_id=team2["id"]
    )

    task = _make_task(client, owner_headers, "Team1 task")

    resp = client.get(f"/tasks/{task['id']}", headers=other_headers)
    assert resp.status_code == 403

    resp = client.get("/tasks", headers=other_headers)
    assert resp.status_code == 200
    assert task["id"] not in [t["id"] for t in resp.json()]


# ---- GET /tasks?team_id= narrows, never widens ------------------------------


def test_team_id_filter_only_narrows_within_existing_visibility(client, auth_headers):
    dept = _create_department(client, auth_headers, "Dept C")
    team1 = _create_team(client, auth_headers, dept["id"], "Team C1")
    team2 = _create_team(client, auth_headers, dept["id"], "Team C2")

    owner1_headers = _register_and_login(
        client, auth_headers, "owner1.filter@example.com", team_id=team1["id"]
    )
    owner2_headers = _register_and_login(
        client, auth_headers, "owner2.filter@example.com", team_id=team2["id"]
    )
    viewer_headers = _register_and_login(
        client, auth_headers, "viewer.filter@example.com", team_id=team1["id"]
    )

    task1 = _make_task(client, owner1_headers, "Team1 task")
    task2 = _make_task(client, owner2_headers, "Team2 task")

    # Team1 teammate: team_id=team1 returns task1, not task2.
    resp = client.get(f"/tasks?team_id={team1['id']}", headers=viewer_headers)
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert task1["id"] in ids
    assert task2["id"] not in ids

    # Filtering by the *other* team, which this viewer has no relation to,
    # returns nothing — the filter can't widen visibility beyond §5.1's grant.
    resp = client.get(f"/tasks?team_id={team2['id']}", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.json() == []

    # Admin sees everything for team2 via the same filter (unaffected).
    resp = client.get(f"/tasks?team_id={team2['id']}", headers=auth_headers)
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert task2["id"] in ids
    assert task1["id"] not in ids


# ---- GET/PATCH /teams/{id}/board-config -------------------------------------


def test_get_team_board_config_lazy_creates_with_defaults(client, auth_headers):
    dept = _create_department(client, auth_headers, "Dept D")
    team = _create_team(client, auth_headers, dept["id"], "Team D")

    resp = client.get(f"/teams/{team['id']}/board-config", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["team_id"] == team["id"]
    assert body["board_name"] is None
    assert body["swimlane_field"] == "assignee"
    assert body["can_manage"] is True  # bootstrap admin holds every permission


def test_get_team_board_config_404_for_nonexistent_team(client, auth_headers):
    resp = client.get("/teams/does-not-exist/board-config", headers=auth_headers)
    assert resp.status_code == 404


def test_patch_team_board_config_rename_and_swimlane_field(client, auth_headers):
    dept = _create_department(client, auth_headers, "Dept E")
    team = _create_team(client, auth_headers, dept["id"], "Team E")

    resp = client.patch(
        f"/teams/{team['id']}/board-config",
        json={"board_name": "Sprint Board", "swimlane_field": "priority"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["board_name"] == "Sprint Board"
    assert body["swimlane_field"] == "priority"
    assert body["can_manage"] is True

    # Persists.
    resp = client.get(f"/teams/{team['id']}/board-config", headers=auth_headers)
    assert resp.json()["board_name"] == "Sprint Board"
    assert resp.json()["swimlane_field"] == "priority"

    # Explicit null clears board_name back to the Team.name fallback.
    resp = client.patch(
        f"/teams/{team['id']}/board-config", json={"board_name": None}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["board_name"] is None
    assert resp.json()["swimlane_field"] == "priority"  # unchanged (omitted key)


def test_patch_team_board_config_persists_independently_per_team_and_from_global(client, auth_headers):
    dept = _create_department(client, auth_headers, "Dept F")
    team1 = _create_team(client, auth_headers, dept["id"], "Team F1")
    team2 = _create_team(client, auth_headers, dept["id"], "Team F2")

    # Set the global config to a non-default value first.
    resp = client.patch("/admin/board-config", json={"swimlane_field": "category"}, headers=auth_headers)
    assert resp.status_code == 200

    client.patch(
        f"/teams/{team1['id']}/board-config",
        json={"board_name": "Team F1 Board", "swimlane_field": "priority"},
        headers=auth_headers,
    )

    team2_config = client.get(f"/teams/{team2['id']}/board-config", headers=auth_headers).json()
    global_config = client.get("/admin/board-config", headers=auth_headers).json()

    # team1's change didn't leak into team2 or the global singleton.
    assert team2_config["board_name"] is None
    assert global_config["swimlane_field"] == "category"

    team1_config = client.get(f"/teams/{team1['id']}/board-config", headers=auth_headers).json()
    assert team1_config["board_name"] == "Team F1 Board"
    assert team1_config["swimlane_field"] == "priority"


def test_patch_team_board_config_403_without_manage_board_config_permission(client, auth_headers):
    dept = _create_department(client, auth_headers, "Dept G")
    team = _create_team(client, auth_headers, dept["id"], "Team G")

    employee_headers = _register_and_login(client, auth_headers, "employee.boardcfg@example.com")

    resp = client.patch(
        f"/teams/{team['id']}/board-config", json={"board_name": "Nope"}, headers=employee_headers
    )
    assert resp.status_code == 403


def test_patch_team_board_config_403_for_the_teams_own_manager_without_permission(client, auth_headers):
    """§5.2 (finalized): admin-only, no team-manager carve-out — the team's
    own manager gets exactly the same 403 a random employee would."""
    dept = _create_department(client, auth_headers, "Dept H")
    team = _create_team(client, auth_headers, dept["id"], "Team H")

    manager_headers = _register_and_login(
        client, auth_headers, "manager.boardcfg@example.com", role="manager", team_id=team["id"]
    )
    # Make this manager the team's own manager.
    manager_id = client.get("/users/me", headers=manager_headers).json()["id"]
    resp = client.patch(f"/teams/{team['id']}", json={"manager_id": manager_id}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["manager_id"] == manager_id

    resp = client.patch(
        f"/teams/{team['id']}/board-config",
        json={"board_name": "Manager's Board"},
        headers=manager_headers,
    )
    assert resp.status_code == 403


def test_can_manage_field_accurate_for_permission_holder_vs_plain_employee_on_both_endpoints(
    client, auth_headers
):
    dept = _create_department(client, auth_headers, "Dept I")
    team = _create_team(client, auth_headers, dept["id"], "Team I")

    role = _create_role(client, auth_headers, "Board Manager")
    _set_permissions(client, auth_headers, role["id"], ["manage_board_config"])

    holder_headers = _register_and_login(
        client, auth_headers, "holder.canmanage@example.com", role_id=role["id"]
    )
    plain_headers = _register_and_login(client, auth_headers, "plain.canmanage@example.com")

    # Global GET /admin/board-config.
    resp = client.get("/admin/board-config", headers=holder_headers)
    assert resp.status_code == 200
    assert resp.json()["can_manage"] is True

    resp = client.get("/admin/board-config", headers=plain_headers)
    assert resp.status_code == 200
    assert resp.json()["can_manage"] is False

    # New GET /teams/{id}/board-config.
    resp = client.get(f"/teams/{team['id']}/board-config", headers=holder_headers)
    assert resp.status_code == 200
    assert resp.json()["can_manage"] is True

    resp = client.get(f"/teams/{team['id']}/board-config", headers=plain_headers)
    assert resp.status_code == 200
    assert resp.json()["can_manage"] is False

    # The permission holder can actually PATCH both.
    resp = client.patch("/admin/board-config", json={"swimlane_field": "assignee"}, headers=holder_headers)
    assert resp.status_code == 200
    resp = client.patch(
        f"/teams/{team['id']}/board-config", json={"board_name": "Held"}, headers=holder_headers
    )
    assert resp.status_code == 200

    # The plain employee cannot.
    resp = client.patch("/admin/board-config", json={"swimlane_field": "category"}, headers=plain_headers)
    assert resp.status_code == 403
    resp = client.patch(
        f"/teams/{team['id']}/board-config", json={"board_name": "Nope"}, headers=plain_headers
    )
    assert resp.status_code == 403
