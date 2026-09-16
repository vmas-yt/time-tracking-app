def test_start_timer(client, auth_headers, task_id):
    resp = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["status"] == "running"


def test_cannot_start_second_timer_for_same_user(client, auth_headers, task_id):
    client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers)
    resp = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers)
    assert resp.status_code == 409


def test_pause_and_resume(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    paused = client.post(f"/time-entries/{entry['id']}/pause", headers=auth_headers)
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = client.post(f"/time-entries/{entry['id']}/resume", headers=auth_headers)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"


def test_cannot_pause_a_paused_timer(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    client.post(f"/time-entries/{entry['id']}/pause", headers=auth_headers)
    resp = client.post(f"/time-entries/{entry['id']}/pause", headers=auth_headers)
    assert resp.status_code == 409


def test_cannot_resume_a_running_timer(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    resp = client.post(f"/time-entries/{entry['id']}/resume", headers=auth_headers)
    assert resp.status_code == 409


def test_stop_from_running(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    resp = client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_stop_from_paused(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    client.post(f"/time-entries/{entry['id']}/pause", headers=auth_headers)
    resp = client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_cannot_transition_out_of_stopped(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)

    for action in ("pause", "resume", "stop"):
        resp = client.post(f"/time-entries/{entry['id']}/{action}", headers=auth_headers)
        assert resp.status_code == 409


def test_stopping_frees_up_a_new_timer(client, auth_headers, task_id):
    entry = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers).json()
    client.post(f"/time-entries/{entry['id']}/stop", headers=auth_headers)
    resp = client.post(f"/time-entries/start?task_id={task_id}", headers=auth_headers)
    assert resp.status_code == 201
