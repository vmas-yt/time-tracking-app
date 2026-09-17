"""Custom field per-type value validation (§1.3) and admin dropdown-option
CRUD, including built-in-option protection (§2.7) — per
docs/design/custom-fields-admin-design.md.
"""


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


def _create_field(client, auth_headers, name, field_type, options=None):
    payload = {"name": name, "field_type": field_type}
    if options is not None:
        payload["options"] = options
    return client.post("/admin/custom-fields", json=payload, headers=auth_headers).json()


def _make_task(client, headers, title="Task", **overrides):
    payload = {"title": title, "category": "meeting"}
    payload.update(overrides)
    return client.post("/tasks", json=payload, headers=headers)


# ---- Custom field type validation (§1.3) -----------------------------------


def test_text_field_accepts_any_string_including_empty(client, auth_headers):
    field = _create_field(client, auth_headers, "Notes", "text")
    resp = _make_task(client, auth_headers, "T1", custom_values={field["id"]: ""})
    assert resp.status_code == 201
    assert resp.json()["custom_values"][field["id"]] == ""


def test_number_field_accepts_numeric_string(client, auth_headers):
    field = _create_field(client, auth_headers, "Story Points", "number")
    resp = _make_task(client, auth_headers, "T2", custom_values={field["id"]: "3.5"})
    assert resp.status_code == 201
    assert resp.json()["custom_values"][field["id"]] == "3.5"


def test_number_field_rejects_non_numeric_string(client, auth_headers):
    field = _create_field(client, auth_headers, "Story Points", "number")
    resp = _make_task(client, auth_headers, "T3", custom_values={field["id"]: "abc"})
    assert resp.status_code == 400
    assert "Story Points" in resp.json()["detail"]


def test_date_field_accepts_iso_date(client, auth_headers):
    field = _create_field(client, auth_headers, "Due", "date")
    resp = _make_task(client, auth_headers, "T4", custom_values={field["id"]: "2026-01-15"})
    assert resp.status_code == 201
    assert resp.json()["custom_values"][field["id"]] == "2026-01-15"


def test_date_field_rejects_non_iso_string(client, auth_headers):
    field = _create_field(client, auth_headers, "Due", "date")
    resp = _make_task(client, auth_headers, "T5", custom_values={field["id"]: "next tuesday"})
    assert resp.status_code == 400


def test_boolean_field_accepts_true_or_false_literal(client, auth_headers):
    field = _create_field(client, auth_headers, "Blocked", "boolean")
    resp = _make_task(client, auth_headers, "T6", custom_values={field["id"]: "true"})
    assert resp.status_code == 201
    assert resp.json()["custom_values"][field["id"]] == "true"


def test_boolean_field_rejects_non_literal_value(client, auth_headers):
    field = _create_field(client, auth_headers, "Blocked", "boolean")
    resp = _make_task(client, auth_headers, "T7", custom_values={field["id"]: "yes"})
    assert resp.status_code == 400


def test_select_field_accepts_active_option_value(client, auth_headers):
    field = _create_field(client, auth_headers, "Category tag", "select", options=["Alpha", "Beta"])
    resp = _make_task(client, auth_headers, "T8", custom_values={field["id"]: "Alpha"})
    assert resp.status_code == 201
    assert resp.json()["custom_values"][field["id"]] == "Alpha"


def test_select_field_rejects_value_that_is_not_an_option(client, auth_headers):
    field = _create_field(client, auth_headers, "Category tag", "select", options=["Alpha", "Beta"])
    resp = _make_task(client, auth_headers, "T9", custom_values={field["id"]: "Legacy"})
    assert resp.status_code == 400
    assert "Category tag" in resp.json()["detail"]


def test_select_field_rejects_deactivated_option(client, auth_headers):
    field = _create_field(client, auth_headers, "Category tag", "select", options=["Alpha", "Beta"])
    options = client.get(
        f"/admin/dropdown-options?scope=custom_field&custom_field_id={field['id']}",
        headers=auth_headers,
    ).json()
    alpha = next(o for o in options if o["value"] == "Alpha")
    client.patch(
        f"/admin/dropdown-options/{alpha['id']}", json={"is_active": False}, headers=auth_headers
    )

    resp = _make_task(client, auth_headers, "T10", custom_values={field["id"]: "Alpha"})
    assert resp.status_code == 400


def test_unknown_custom_field_id_is_400(client, auth_headers):
    resp = _make_task(client, auth_headers, "T11", custom_values={"nonexistent-field": "x"})
    assert resp.status_code == 400


def test_custom_values_settable_at_creation_in_one_call(client, auth_headers):
    """§1.2/§1.3 — no more create-then-patch round trip needed."""
    field = _create_field(client, auth_headers, "Ticket #", "text")
    resp = _make_task(client, auth_headers, "T12", custom_values={field["id"]: "TT-42"})
    assert resp.status_code == 201
    assert resp.json()["custom_values"][field["id"]] == "TT-42"


def test_patch_task_custom_values_tightened_validation(client, auth_headers, task_id):
    """PATCH now runs the same per-type validation as POST (§1.3)."""
    field = _create_field(client, auth_headers, "Due", "date")
    resp = client.patch(
        f"/tasks/{task_id}", json={"custom_values": {field["id"]: "not-a-date"}}, headers=auth_headers
    )
    assert resp.status_code == 400


# ---- Dropdown option CRUD (§2.7) -------------------------------------------


def test_list_dropdown_options_requires_scope(client, auth_headers):
    resp = client.get("/admin/dropdown-options", headers=auth_headers)
    assert resp.status_code == 400


def test_list_dropdown_options_rejects_invalid_scope(client, auth_headers):
    resp = client.get("/admin/dropdown-options?scope=bogus", headers=auth_headers)
    assert resp.status_code == 400


def test_list_task_category_options_includes_seeded_builtins(client, auth_headers):
    resp = client.get("/admin/dropdown-options?scope=task_category", headers=auth_headers)
    assert resp.status_code == 200
    values = {o["value"] for o in resp.json()}
    assert "meeting" in values
    assert "other" in values
    assert all(o["is_builtin"] for o in resp.json())


def test_list_custom_field_scope_requires_custom_field_id(client, auth_headers):
    resp = client.get("/admin/dropdown-options?scope=custom_field", headers=auth_headers)
    assert resp.status_code == 400


def test_list_custom_field_scope_rejects_non_select_field(client, auth_headers):
    field = _create_field(client, auth_headers, "Notes", "text")
    resp = client.get(
        f"/admin/dropdown-options?scope=custom_field&custom_field_id={field['id']}",
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_non_admin_cannot_create_dropdown_option(client, auth_headers):
    employee_headers = _create_employee(client, auth_headers, "dd_emp1@example.com")
    resp = client.post(
        "/admin/dropdown-options",
        json={"scope": "task_category", "value": "vendor_escalation"},
        headers=employee_headers,
    )
    assert resp.status_code == 403


def test_admin_can_add_new_category_option(client, auth_headers):
    resp = client.post(
        "/admin/dropdown-options",
        json={"scope": "task_category", "value": "vendor_escalation", "label": "Vendor Escalation"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_builtin"] is False
    assert body["is_active"] is True
    assert body["label"] == "Vendor Escalation"

    # And it's now usable as a task's category.
    resp = _make_task(client, auth_headers, "Escalated", category="vendor_escalation")
    assert resp.status_code == 201


def test_create_dropdown_option_label_defaults_to_value(client, auth_headers):
    resp = client.post(
        "/admin/dropdown-options",
        json={"scope": "task_priority", "value": "low"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["label"] == "low"


def test_create_dropdown_option_rejects_duplicate(client, auth_headers):
    client.post(
        "/admin/dropdown-options",
        json={"scope": "task_priority", "value": "critical"},
        headers=auth_headers,
    )
    resp = client.post(
        "/admin/dropdown-options",
        json={"scope": "task_priority", "value": "critical"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_create_dropdown_option_for_custom_field_requires_select_type(client, auth_headers):
    field = _create_field(client, auth_headers, "Notes", "text")
    resp = client.post(
        "/admin/dropdown-options",
        json={"scope": "custom_field", "custom_field_id": field["id"], "value": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_create_dropdown_option_custom_field_id_required_for_custom_field_scope(client, auth_headers):
    resp = client.post(
        "/admin/dropdown-options", json={"scope": "custom_field", "value": "x"}, headers=auth_headers
    )
    assert resp.status_code == 400


def test_create_dropdown_option_custom_field_id_rejected_for_non_custom_field_scope(client, auth_headers):
    field = _create_field(client, auth_headers, "Tag", "select", options=["A"])
    resp = client.post(
        "/admin/dropdown-options",
        json={"scope": "task_category", "custom_field_id": field["id"], "value": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_patch_dropdown_option_can_rename_label(client, auth_headers):
    created = client.post(
        "/admin/dropdown-options",
        json={"scope": "task_priority", "value": "urgent"},
        headers=auth_headers,
    ).json()
    resp = client.patch(
        f"/admin/dropdown-options/{created['id']}", json={"label": "Urgent!"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "Urgent!"
    assert resp.json()["value"] == "urgent"


def test_patch_dropdown_option_404_when_missing(client, auth_headers):
    resp = client.patch(
        "/admin/dropdown-options/does-not-exist", json={"label": "x"}, headers=auth_headers
    )
    assert resp.status_code == 404


def test_cannot_deactivate_builtin_category_option(client, auth_headers):
    options = client.get("/admin/dropdown-options?scope=task_category", headers=auth_headers).json()
    meeting = next(o for o in options if o["value"] == "meeting")
    resp = client.patch(
        f"/admin/dropdown-options/{meeting['id']}", json={"is_active": False}, headers=auth_headers
    )
    assert resp.status_code == 409


def test_cannot_deactivate_other_category_option_special_message(client, auth_headers):
    options = client.get("/admin/dropdown-options?scope=task_category", headers=auth_headers).json()
    other = next(o for o in options if o["value"] == "other")
    resp = client.patch(
        f"/admin/dropdown-options/{other['id']}", json={"is_active": False}, headers=auth_headers
    )
    assert resp.status_code == 409
    assert "category_other_text" in resp.json()["detail"]


def test_cannot_deactivate_builtin_priority_option(client, auth_headers):
    options = client.get("/admin/dropdown-options?scope=task_priority", headers=auth_headers).json()
    normal = next(o for o in options if o["value"] == "normal")
    resp = client.delete(f"/admin/dropdown-options/{normal['id']}", headers=auth_headers)
    assert resp.status_code == 409


def test_delete_dropdown_option_soft_deactivates_non_builtin(client, auth_headers):
    created = client.post(
        "/admin/dropdown-options",
        json={"scope": "task_priority", "value": "low2"},
        headers=auth_headers,
    ).json()
    resp = client.delete(f"/admin/dropdown-options/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    # Still resolvable by id afterward (soft-delete, not gone).
    listed = client.get(
        "/admin/dropdown-options?scope=task_priority&include_inactive=true", headers=auth_headers
    ).json()
    assert any(o["id"] == created["id"] and o["is_active"] is False for o in listed)


def test_non_admin_include_inactive_is_ignored(client, auth_headers):
    created = client.post(
        "/admin/dropdown-options",
        json={"scope": "task_priority", "value": "low3"},
        headers=auth_headers,
    ).json()
    client.delete(f"/admin/dropdown-options/{created['id']}", headers=auth_headers)

    employee_headers = _create_employee(client, auth_headers, "dd_emp2@example.com")
    listed = client.get(
        "/admin/dropdown-options?scope=task_priority&include_inactive=true", headers=employee_headers
    ).json()
    assert not any(o["id"] == created["id"] for o in listed)


def test_task_creation_rejects_invalid_category(client, auth_headers):
    resp = _make_task(client, auth_headers, "Bad category", category="not_a_real_category")
    assert resp.status_code == 400


def test_task_creation_rejects_invalid_priority(client, auth_headers):
    resp = _make_task(client, auth_headers, "Bad priority", priority="not_a_real_priority")
    assert resp.status_code == 400


def test_patch_task_rejects_invalid_category(client, auth_headers, task_id):
    resp = client.patch(f"/tasks/{task_id}", json={"category": "bogus"}, headers=auth_headers)
    assert resp.status_code == 400


# ---- Custom field response shape & cascade delete --------------------------


def test_custom_field_read_options_shape_is_dropdown_option_objects(client, auth_headers):
    field = _create_field(client, auth_headers, "Tag", "select", options=["A", "B"])
    listed = client.get("/admin/custom-fields", headers=auth_headers).json()
    found = next(f for f in listed if f["id"] == field["id"])
    assert isinstance(found["options"], list)
    assert {o["value"] for o in found["options"]} == {"A", "B"}
    for opt in found["options"]:
        assert "label" in opt and "is_active" in opt and "position" in opt


def test_non_select_field_options_is_null(client, auth_headers):
    field = _create_field(client, auth_headers, "Notes", "text")
    listed = client.get("/admin/custom-fields", headers=auth_headers).json()
    found = next(f for f in listed if f["id"] == field["id"])
    assert found["options"] is None


def test_delete_custom_field_cascades_dropdown_options(client, auth_headers, db_engine):
    from sqlalchemy.orm import sessionmaker

    from app.models import DropdownOption

    field = _create_field(client, auth_headers, "Tag", "select", options=["A", "B"])
    resp = client.delete(f"/admin/custom-fields/{field['id']}", headers=auth_headers)
    assert resp.status_code == 204

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        remaining = (
            db.query(DropdownOption).filter(DropdownOption.custom_field_id == field["id"]).all()
        )
        assert remaining == []
    finally:
        db.close()
