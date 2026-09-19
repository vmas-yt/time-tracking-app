"""Manual/retroactive time-logging feature: `POST /tasks/manual-log`,
`POST /tasks/{task_id}/manual-log`, and `GET`/`PATCH /admin/manual-entry-settings`.

See docs/PRD.md's Timer Logic section and the manual-time-logging design's
"decisions already made" for the exact invariants under test:

  * the N-day window checks Start Date only; Completion Date is
    independently validated as >= start_date and <= today.
  * a manual log is terminal, exactly like Stop.
  * manual and live tracking are mutually exclusive per task (zero existing
    TimeEntry rows of any kind).
  * the completion TaskStatusEvent is backdated to the Completion Date.
  * archived tasks are blocked (409).
  * duration is independently trusted but a coarse impossibility guard
    applies.
"""

from datetime import date, timedelta

from sqlalchemy.orm import sessionmaker

from app.models import TaskStatusEvent


def _register(client, auth_headers, email, full_name="User", role="employee"):
    client.post(
        "/users",
        json={"email": email, "full_name": full_name, "password": "password123", "role": role},
        headers=auth_headers,
    )
    token = client.post(
        "/auth/login", data={"username": email, "password": "password123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _make_task(client, headers, title="Task", **overrides):
    payload = {"title": title, "category": "meeting"}
    payload.update(overrides)
    return client.post("/tasks", json=payload, headers=headers).json()


def _status_events(db_engine, task_id):
    """Returns unordered; most tests here match on the (from, to) pair set
    rather than assuming `occurred_at` order reflects insertion order,
    since the completion event is backdated to Completion Date. For the
    new-task path this is guaranteed <= the (also backdated, to Start Date)
    creation event's occurred_at — see
    routers/tasks.py::create_manual_log_task's docstring for why that
    matters (a real, previously-universal Cumulative Flow bug, not just a
    defensive habit) — but a bounded edge case remains for the
    existing-task path; see services/tasks.py::create_manual_entry's
    docstring."""
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        return db.query(TaskStatusEvent).filter(TaskStatusEvent.task_id == task_id).all()
    finally:
        db.close()


def _iso(d: date) -> str:
    return d.isoformat()


# ---- Happy paths -------------------------------------------------------------


def test_manual_log_on_existing_task_happy_path(client, auth_headers, backlog_task_id):
    start = date.today() - timedelta(days=2)
    completion = date.today()
    resp = client.post(
        f"/tasks/{backlog_task_id}/manual-log",
        json={
            "start_date": _iso(start),
            "completion_date": _iso(completion),
            "duration_minutes": 120,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task = resp.json()
    assert task["status"] == "completed"
    assert task["is_manual_entry"] is True
    assert task["started_at"].startswith(_iso(start))
    assert task["completed_at"].startswith(_iso(completion))
    assert task["total_logged_seconds"] == 120 * 60


def test_manual_log_creates_new_task_happy_path(client, auth_headers):
    start = date.today() - timedelta(days=3)
    completion = date.today() - timedelta(days=1)
    resp = client.post(
        "/tasks/manual-log",
        json={
            "title": "Retroactive task",
            "category": "meeting",
            "start_date": _iso(start),
            "completion_date": _iso(completion),
            "duration_minutes": 90,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task = resp.json()
    assert task["title"] == "Retroactive task"
    assert task["status"] == "completed"
    assert task["is_manual_entry"] is True
    assert task["total_logged_seconds"] == 90 * 60


# ---- Date/duration validation --------------------------------------------------


def test_n_day_boundary_exact(client, auth_headers, backlog_task_id):
    resp = client.patch(
        "/admin/manual-entry-settings", json={"max_days_back": 5}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["max_days_back"] == 5

    ok_task = _make_task(client, auth_headers, "Within window")
    resp = client.post(
        f"/tasks/{ok_task['id']}/manual-log",
        json={
            "start_date": _iso(date.today() - timedelta(days=5)),
            "completion_date": _iso(date.today()),
            "duration_minutes": 30,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201

    bad_task = _make_task(client, auth_headers, "Outside window")
    resp = client.post(
        f"/tasks/{bad_task['id']}/manual-log",
        json={
            "start_date": _iso(date.today() - timedelta(days=6)),
            "completion_date": _iso(date.today()),
            "duration_minutes": 30,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "5 days" in resp.json()["detail"]


def test_completion_date_in_future_rejected(client, auth_headers, backlog_task_id):
    resp = client.post(
        f"/tasks/{backlog_task_id}/manual-log",
        json={
            "start_date": _iso(date.today()),
            "completion_date": _iso(date.today() + timedelta(days=1)),
            "duration_minutes": 30,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_start_date_in_future_rejected(client, auth_headers, backlog_task_id):
    resp = client.post(
        f"/tasks/{backlog_task_id}/manual-log",
        json={
            "start_date": _iso(date.today() + timedelta(days=1)),
            "completion_date": _iso(date.today() + timedelta(days=1)),
            "duration_minutes": 30,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_completion_before_start_rejected(client, auth_headers, backlog_task_id):
    resp = client.post(
        f"/tasks/{backlog_task_id}/manual-log",
        json={
            "start_date": _iso(date.today()),
            "completion_date": _iso(date.today() - timedelta(days=1)),
            "duration_minutes": 30,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_duration_impossibility_guard(client, auth_headers, backlog_task_id):
    """1-day span (start == completion) can hold at most 24h = 1440 minutes."""
    resp = client.post(
        f"/tasks/{backlog_task_id}/manual-log",
        json={
            "start_date": _iso(date.today()),
            "completion_date": _iso(date.today()),
            "duration_minutes": 1441,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400

    ok_task = _make_task(client, auth_headers, "Exactly one day")
    resp = client.post(
        f"/tasks/{ok_task['id']}/manual-log",
        json={
            "start_date": _iso(date.today()),
            "completion_date": _iso(date.today()),
            "duration_minutes": 1440,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201


# ---- Existing-task endpoint preconditions --------------------------------------


def _valid_body():
    return {
        "start_date": _iso(date.today() - timedelta(days=1)),
        "completion_date": _iso(date.today()),
        "duration_minutes": 60,
    }


def test_manual_log_404_for_missing_task(client, auth_headers):
    resp = client.post("/tasks/does-not-exist/manual-log", json=_valid_body(), headers=auth_headers)
    assert resp.status_code == 404


def test_manual_log_403_for_unrelated_user(client, auth_headers):
    owner_headers = _register(client, auth_headers, "manual-owner@example.com")
    outsider_headers = _register(client, auth_headers, "manual-outsider@example.com")
    task = _make_task(client, owner_headers, "Owner task")

    resp = client.post(
        f"/tasks/{task['id']}/manual-log", json=_valid_body(), headers=outsider_headers
    )
    assert resp.status_code == 403


# ---- Attribution: assignee-only, mirroring start_timer's own restriction ----
# Regression coverage for a real bug senior-qa found: `add_manual_log` used to
# accept anyone `assert_can_edit_task` allows (assignee, creator, or admin),
# but `create_manual_entry` unconditionally attributes the resulting
# TimeEntry to the *caller* -- so a creator or admin logging time on a task
# assigned to someone else would silently log hours under their own
# identity for work nominally assigned to (and completed under the name of)
# someone who never touched it, corrupting that person's own time-entry
# history and falsely flagging them as never having logged time in
# `GET /notifications/reminders`. Fixed by tightening both manual-log
# endpoints to assignee-only, exactly like `start_timer`.


def test_manual_log_403_for_creator_who_is_not_assignee(client, auth_headers):
    """The task's creator -- who `assert_can_edit_task` would otherwise
    allow to edit the task -- must NOT be able to manually log time against
    it once assigned to someone else; only the assignee may."""
    assignee_headers = _register(client, auth_headers, "manual-assignee@example.com")
    assignee_id = client.get("/users/me", headers=assignee_headers).json()["id"]
    task = _make_task(client, auth_headers, "Creator's task", assignee_id=assignee_id)

    resp = client.post(f"/tasks/{task['id']}/manual-log", json=_valid_body(), headers=auth_headers)
    assert resp.status_code == 403


def test_manual_log_403_for_admin_who_is_not_assignee(client, auth_headers):
    """Admin doesn't bypass this either -- same as `start_timer`."""
    owner_headers = _register(client, auth_headers, "manual-owner2@example.com")
    admin_id = client.get("/users/me", headers=auth_headers).json()["id"]
    task = _make_task(client, owner_headers, "Owner's own task")
    assert task["assignee_id"] != admin_id

    resp = client.post(f"/tasks/{task['id']}/manual-log", json=_valid_body(), headers=auth_headers)
    assert resp.status_code == 403


def test_manual_log_new_task_403_when_assignee_is_someone_else(client, auth_headers):
    """`POST /tasks/manual-log` with an explicit assignee_id naming someone
    other than the caller must be rejected -- otherwise the caller could
    create a task "for" someone else while still attributing the logged
    hours to themselves."""
    other_headers = _register(client, auth_headers, "manual-other@example.com")
    other_id = client.get("/users/me", headers=other_headers).json()["id"]

    resp = client.post(
        "/tasks/manual-log",
        json={
            "title": "For someone else",
            "category": "meeting",
            "assignee_id": other_id,
            **_valid_body(),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 403


def test_manual_log_time_entry_attributed_to_assignee(client, auth_headers, db_engine):
    """Happy path (assignee logging their own task): the resulting
    TimeEntry.user_id is the assignee/actor, confirming attribution is
    correct once the caller *is* the assignee."""
    from sqlalchemy.orm import sessionmaker

    from app.models import TimeEntry

    assignee_headers = _register(client, auth_headers, "manual-self@example.com")
    assignee_id = client.get("/users/me", headers=assignee_headers).json()["id"]
    task = _make_task(client, assignee_headers, "Self-assigned task")

    resp = client.post(f"/tasks/{task['id']}/manual-log", json=_valid_body(), headers=assignee_headers)
    assert resp.status_code == 201

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        entry = db.query(TimeEntry).filter(TimeEntry.task_id == task["id"]).one()
        assert entry.user_id == assignee_id
    finally:
        db.close()


def test_manual_log_409_for_archived_task(client, auth_headers, backlog_task_id):
    client.post(f"/tasks/{backlog_task_id}/archive", headers=auth_headers)
    resp = client.post(
        f"/tasks/{backlog_task_id}/manual-log", json=_valid_body(), headers=auth_headers
    )
    assert resp.status_code == 409
    assert "archived" in resp.json()["detail"].lower()


def test_manual_log_409_for_already_completed_task(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)

    resp = client.post(f"/tasks/{task_id}/manual-log", json=_valid_body(), headers=auth_headers)
    assert resp.status_code == 409
    assert "already completed" in resp.json()["detail"].lower()


def test_manual_log_409_generic_for_in_progress_open_entry(client, auth_headers, task_id):
    client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers)

    resp = client.post(f"/tasks/{task_id}/manual-log", json=_valid_body(), headers=auth_headers)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "paused timer" not in detail
    assert "already has a time entry" in detail.lower()


def test_manual_log_409_specific_for_on_hold_paused_entry(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    client.patch(f"/tasks/{task_id}", json={"status": "on_hold"}, headers=auth_headers)

    resp = client.post(f"/tasks/{task_id}/manual-log", json=_valid_body(), headers=auth_headers)
    assert resp.status_code == 409
    assert "paused timer" in resp.json()["detail"]


# ---- Terminal effect ------------------------------------------------------------


def test_manual_log_is_terminal_no_further_timer_action(client, auth_headers, backlog_task_id):
    resp = client.post(
        f"/tasks/{backlog_task_id}/manual-log", json=_valid_body(), headers=auth_headers
    )
    assert resp.status_code == 201

    resp = client.post(f"/time-entries/start?task_id={backlog_task_id}", headers=auth_headers)
    assert resp.status_code == 409

    for new_status in ("backlog", "todo", "on_hold"):
        resp = client.patch(
            f"/tasks/{backlog_task_id}", json={"status": new_status}, headers=auth_headers
        )
        assert resp.status_code == 409


# ---- Audit rows / status events --------------------------------------------------


def test_audit_rows_and_status_events_existing_task_path(client, auth_headers, backlog_task_id, db_engine):
    start = date.today() - timedelta(days=1)
    completion = date.today()
    resp = client.post(
        f"/tasks/{backlog_task_id}/manual-log",
        json={"start_date": _iso(start), "completion_date": _iso(completion), "duration_minutes": 125},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    audit = client.get(f"/tasks/{backlog_task_id}/audit", headers=auth_headers).json()
    actions = [a["action"] for a in audit]
    assert actions == ["created", "status_changed", "manual_time_logged"]
    assert "2h 5m" in audit[-1]["detail"]
    assert start.isoformat() in audit[-1]["detail"]
    assert completion.isoformat() in audit[-1]["detail"]

    events = _status_events(db_engine, backlog_task_id)
    pairs = {(e.from_status.value if e.from_status else None, e.to_status.value) for e in events}
    assert pairs == {(None, "backlog"), ("backlog", "completed")}
    # The completion event is backdated to the Completion Date, not "now".
    completion_event = next(e for e in events if e.to_status.value == "completed")
    assert completion_event.occurred_at.date() == completion


def test_audit_rows_and_status_events_new_task_path(client, auth_headers, db_engine):
    start = date.today() - timedelta(days=4)
    completion = date.today() - timedelta(days=2)
    resp = client.post(
        "/tasks/manual-log",
        json={
            "title": "New manual task",
            "category": "meeting",
            "start_date": _iso(start),
            "completion_date": _iso(completion),
            "duration_minutes": 45,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task = resp.json()

    audit = client.get(f"/tasks/{task['id']}/audit", headers=auth_headers).json()
    actions = [a["action"] for a in audit]
    assert actions == ["created", "status_changed", "manual_time_logged"]

    events = _status_events(db_engine, task["id"])
    pairs = {(e.from_status.value if e.from_status else None, e.to_status.value) for e in events}
    assert pairs == {(None, "backlog"), ("backlog", "completed")}
    completion_event = next(e for e in events if e.to_status.value == "completed")
    assert completion_event.occurred_at.date() == completion


# ---- card_date --------------------------------------------------------------------


def test_card_date_not_started_task_uses_created_at(client, auth_headers, backlog_task_id):
    task = client.get(f"/tasks/{backlog_task_id}", headers=auth_headers).json()
    assert task["card_date"] == task["created_at"]


def test_card_date_started_task_uses_started_at(client, auth_headers, task_id):
    client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers)
    task = client.get(f"/tasks/{task_id}", headers=auth_headers).json()
    assert task["started_at"] is not None
    assert task["card_date"] == task["started_at"]
    assert task["card_date"] != task["created_at"]


def test_card_date_completed_task_uses_completed_at(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)
    task = client.get(f"/tasks/{task_id}", headers=auth_headers).json()
    assert task["card_date"] == task["completed_at"]


def test_card_date_manual_task_uses_completed_at(client, auth_headers, backlog_task_id):
    resp = client.post(
        f"/tasks/{backlog_task_id}/manual-log", json=_valid_body(), headers=auth_headers
    )
    task = resp.json()
    assert task["card_date"] == task["completed_at"]


# ---- Reporting: Lead Time excludes manual tasks; Cycle Time already does -------


def test_lead_time_excludes_manual_task_with_backdated_completion(client, auth_headers, backlog_task_id):
    # Completion date far enough in the past that completed_at < created_at
    # for the *real* row-insertion time, which would otherwise corrupt Lead
    # Time with a negative/near-zero duration.
    start = date.today() - timedelta(days=6)
    completion = date.today() - timedelta(days=6)
    client.patch("/admin/manual-entry-settings", json={"max_days_back": 7}, headers=auth_headers)
    resp = client.post(
        f"/tasks/{backlog_task_id}/manual-log",
        json={"start_date": _iso(start), "completion_date": _iso(completion), "duration_minutes": 30},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    lead_time = client.get("/reports/lead-time", headers=auth_headers).json()
    assert backlog_task_id not in {p["task_id"] for p in lead_time}


def test_cycle_time_already_excludes_manual_task(client, auth_headers, backlog_task_id):
    resp = client.post(
        f"/tasks/{backlog_task_id}/manual-log", json=_valid_body(), headers=auth_headers
    )
    assert resp.status_code == 201

    cycle_time = client.get("/reports/cycle-time", headers=auth_headers).json()
    assert backlog_task_id not in {p["task_id"] for p in cycle_time}


# ---- Admin settings endpoints -----------------------------------------------------


def test_get_manual_entry_settings_default(client, auth_headers):
    resp = client.get("/admin/manual-entry-settings", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_days_back"] == 7
    assert "updated_at" in body


def test_get_manual_entry_settings_any_authenticated_user(client, auth_headers):
    employee_headers = _register(client, auth_headers, "settings-reader@example.com")
    resp = client.get("/admin/manual-entry-settings", headers=employee_headers)
    assert resp.status_code == 200
    assert resp.json()["max_days_back"] == 7


def test_patch_manual_entry_settings_requires_admin(client, auth_headers):
    employee_headers = _register(client, auth_headers, "settings-writer@example.com")
    resp = client.patch(
        "/admin/manual-entry-settings", json={"max_days_back": 3}, headers=employee_headers
    )
    assert resp.status_code == 403


def test_patch_manual_entry_settings_zero_is_valid(client, auth_headers):
    resp = client.patch("/admin/manual-entry-settings", json={"max_days_back": 0}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["max_days_back"] == 0


def test_patch_manual_entry_settings_negative_rejected(client, auth_headers):
    resp = client.patch("/admin/manual-entry-settings", json={"max_days_back": -1}, headers=auth_headers)
    assert resp.status_code == 422


def test_changing_max_days_back_changes_what_a_request_accepts(client, auth_headers, backlog_task_id):
    """End-to-end: no redeploy needed — PATCHing the setting immediately
    changes what the next manual-log request's date validation accepts."""
    body = {
        "start_date": _iso(date.today() - timedelta(days=3)),
        "completion_date": _iso(date.today()),
        "duration_minutes": 30,
    }

    client.patch("/admin/manual-entry-settings", json={"max_days_back": 2}, headers=auth_headers)
    resp = client.post(f"/tasks/{backlog_task_id}/manual-log", json=body, headers=auth_headers)
    assert resp.status_code == 400

    client.patch("/admin/manual-entry-settings", json={"max_days_back": 3}, headers=auth_headers)
    resp = client.post(f"/tasks/{backlog_task_id}/manual-log", json=body, headers=auth_headers)
    assert resp.status_code == 201


def test_new_task_manual_log_creation_event_ordered_before_completion_event(client, auth_headers, db_engine):
    """Regression: `POST /tasks/manual-log`'s None->Backlog creation event
    used to default to real "now", while the Backlog->Completed event is
    always backdated to Completion Date (<= today, per validation). Since
    midnight-of-today-or-earlier is always <= real "now", the completion
    event would sort *before* the creation event in every single call to
    this endpoint (not a rare edge case) -- and reports.py::cumulative_flow
    replays TaskStatusEvent rows in ascending occurred_at order, letting the
    last-processed event win, so the later-sorted-but-logically-earlier
    creation event would permanently overwrite the task's replayed status
    back to Backlog. Fixed by backdating the creation event to Start Date
    too, so start_date <= completion_date (already validated) guarantees
    correct ascending order. Verified two ways: the raw event ordering, and
    the actual /reports/cumulative-flow endpoint showing the task as
    completed, not backlog, today."""
    completion = date.today()
    resp = client.post(
        "/tasks/manual-log",
        json={
            "title": "Same-day manual task",
            "category": "meeting",
            "start_date": _iso(completion),
            "completion_date": _iso(completion),
            "duration_minutes": 30,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task = resp.json()

    events = sorted(_status_events(db_engine, task["id"]), key=lambda e: e.occurred_at)
    assert [e.to_status.value for e in events] == ["backlog", "completed"]
    creation_event, completion_event = events
    assert creation_event.occurred_at <= completion_event.occurred_at

    flow = client.get("/reports/cumulative-flow", params={"days": 1}, headers=auth_headers).json()
    assert flow, "expected at least today's snapshot"
    todays_counts = flow[-1]["counts"]
    assert todays_counts.get("completed", 0) >= 1
    assert todays_counts.get("backlog", 0) == 0
