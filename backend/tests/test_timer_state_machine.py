"""Timer + task status state machine, per docs/PRD.md 'Timer Logic'.

    Start:  TODO|ON_HOLD (no open entry)  -> IN_PROGRESS, new RUNNING entry
    Pause:  RUNNING                        -> task status unchanged, entry PAUSED
    Resume: PAUSED, task ON_HOLD           -> task IN_PROGRESS, entry RUNNING
    Resume: PAUSED, task IN_PROGRESS       -> task unchanged,   entry RUNNING
    Stop:   RUNNING|PAUSED                 -> task COMPLETED (terminal), entry STOPPED
    Manual On Hold from IN_PROGRESS auto-pauses the running entry.
    Only one RUNNING entry per user; PAUSED entries may coexist across tasks.
"""


def start(client, auth_headers, task_id):
    return client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers)


def test_start_from_todo_moves_task_to_in_progress(client, auth_headers, task_id):
    resp = start(client, auth_headers, task_id)
    assert resp.status_code == 201
    assert resp.json()["status"] == "running"
    task = client.get(f"/tasks/{task_id}", headers=auth_headers).json()
    assert task["status"] == "in_progress"


def test_cannot_start_from_backlog(client, auth_headers, backlog_task_id):
    resp = start(client, auth_headers, backlog_task_id)
    assert resp.status_code == 409


def test_cannot_start_two_running_timers_for_same_user(client, auth_headers, task_id):
    start(client, auth_headers, task_id)
    other_task = client.post(
        "/tasks", json={"title": "Other", "category": "meeting"}, headers=auth_headers
    ).json()
    client.patch(f"/tasks/{other_task['id']}", json={"status": "todo"}, headers=auth_headers)

    resp = start(client, auth_headers, other_task["id"])
    assert resp.status_code == 409


def test_cannot_start_a_task_that_already_has_an_open_entry(client, auth_headers, task_id):
    start(client, auth_headers, task_id)
    resp = start(client, auth_headers, task_id)
    assert resp.status_code == 409


def test_pause_does_not_change_task_status(client, auth_headers, task_id):
    entry = start(client, auth_headers, task_id).json()
    resp = client.post(f"/time-entries/{entry['id']}/pause", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"

    task = client.get(f"/tasks/{task_id}", headers=auth_headers).json()
    assert task["status"] == "in_progress"


def test_resume_after_plain_pause_keeps_task_in_progress(client, auth_headers, task_id):
    entry = start(client, auth_headers, task_id).json()
    client.post(f"/time-entries/{entry['id']}/pause", headers=auth_headers)
    resp = client.post(f"/time-entries/{entry['id']}/resume", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"

    task = client.get(f"/tasks/{task_id}", headers=auth_headers).json()
    assert task["status"] == "in_progress"


def test_cannot_pause_a_paused_or_stopped_timer(client, auth_headers, task_id):
    entry = start(client, auth_headers, task_id).json()
    client.post(f"/time-entries/{entry['id']}/pause", headers=auth_headers)
    assert client.post(f"/time-entries/{entry['id']}/pause", headers=auth_headers).status_code == 409

    client.post(f"/time-entries/{entry['id']}/resume", headers=auth_headers)
    client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)
    assert client.post(f"/time-entries/{entry['id']}/pause", headers=auth_headers).status_code == 409


def test_manual_on_hold_auto_pauses_running_timer(client, auth_headers, task_id):
    entry = start(client, auth_headers, task_id).json()
    resp = client.patch(f"/tasks/{task_id}", json={"status": "on_hold"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "on_hold"

    entries = client.get("/time-entries/open", headers=auth_headers).json()
    assert len(entries) == 1
    assert entries[0]["id"] == entry["id"]
    assert entries[0]["status"] == "paused"


def test_resume_from_on_hold_goes_directly_to_in_progress(client, auth_headers, task_id):
    entry = start(client, auth_headers, task_id).json()
    client.patch(f"/tasks/{task_id}", json={"status": "on_hold"}, headers=auth_headers)

    resp = client.post(f"/time-entries/{entry['id']}/resume", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"

    task = client.get(f"/tasks/{task_id}", headers=auth_headers).json()
    assert task["status"] == "in_progress"


def test_backlog_can_go_directly_to_on_hold_then_start(client, auth_headers, backlog_task_id):
    resp = client.patch(f"/tasks/{backlog_task_id}", json={"status": "on_hold"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "on_hold"

    # No timer ever ran, so there's no open entry to resume — Start begins a
    # fresh one, per PRD ("Start ... only works from To Do or On Hold").
    resp = start(client, auth_headers, backlog_task_id)
    assert resp.status_code == 201
    task = client.get(f"/tasks/{backlog_task_id}", headers=auth_headers).json()
    assert task["status"] == "in_progress"


def test_cannot_manually_leave_on_hold_while_timer_open(client, auth_headers, task_id):
    start(client, auth_headers, task_id)
    client.patch(f"/tasks/{task_id}", json={"status": "on_hold"}, headers=auth_headers)

    resp = client.patch(f"/tasks/{task_id}", json={"status": "todo"}, headers=auth_headers)
    assert resp.status_code == 409


def test_stop_marks_task_completed_permanently(client, auth_headers, task_id):
    entry = start(client, auth_headers, task_id).json()
    resp = client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"

    task = client.get(f"/tasks/{task_id}", headers=auth_headers).json()
    assert task["status"] == "completed"

    for action in ("pause", "resume", "stop"):
        assert client.post(f"/time-entries/{entry['id']}/{action}", headers=auth_headers).status_code == 409
    for new_status in ("backlog", "todo", "on_hold"):
        assert (
            client.patch(f"/tasks/{task_id}", json={"status": new_status}, headers=auth_headers).status_code
            == 409
        )


def test_stop_from_on_hold_paused_entry_completes_task(client, auth_headers, task_id):
    entry = start(client, auth_headers, task_id).json()
    client.patch(f"/tasks/{task_id}", json={"status": "on_hold"}, headers=auth_headers)

    resp = client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)
    assert resp.status_code == 200

    task = client.get(f"/tasks/{task_id}", headers=auth_headers).json()
    assert task["status"] == "completed"


def test_pausing_one_task_frees_up_starting_another(client, auth_headers, task_id):
    """Multiple tasks may be In Progress/On Hold in parallel — only one
    timer may be RUNNING at a time."""
    entry = start(client, auth_headers, task_id).json()
    client.post(f"/time-entries/{entry['id']}/pause", headers=auth_headers)

    other_task = client.post(
        "/tasks", json={"title": "Other", "category": "meeting"}, headers=auth_headers
    ).json()
    client.patch(f"/tasks/{other_task['id']}", json={"status": "todo"}, headers=auth_headers)

    resp = start(client, auth_headers, other_task["id"])
    assert resp.status_code == 201

    open_entries = client.get("/time-entries/open", headers=auth_headers).json()
    assert len(open_entries) == 2
    statuses = {e["status"] for e in open_entries}
    assert statuses == {"paused", "running"}


def test_audit_trail_records_lifecycle(client, auth_headers, task_id):
    entry = start(client, auth_headers, task_id).json()
    client.post(f"/time-entries/{entry['id']}/pause", headers=auth_headers)
    client.post(f"/time-entries/{entry['id']}/resume", headers=auth_headers)
    client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)

    audit = client.get(f"/tasks/{task_id}/audit", headers=auth_headers).json()
    actions = [a["action"] for a in audit]
    assert actions == [
        "created",
        "status_changed",
        "status_changed",
        "timer_started",
        "timer_paused",
        "timer_resumed",
        "status_changed",
        "timer_stopped",
    ]


def test_comments_are_listed_in_order(client, auth_headers, task_id):
    client.post(f"/tasks/{task_id}/comments", json={"body": "first"}, headers=auth_headers)
    client.post(f"/tasks/{task_id}/comments", json={"body": "second"}, headers=auth_headers)

    comments = client.get(f"/tasks/{task_id}/comments", headers=auth_headers).json()
    assert [c["body"] for c in comments] == ["first", "second"]
