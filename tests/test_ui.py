"""Smoke tests for the server-rendered web UI."""


def test_root_redirects_to_ui(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/ui"


def test_dashboard_renders(client):
    resp = client.get("/ui")
    assert resp.status_code == 200
    assert "Workflows" in resp.text
    assert "text/html" in resp.headers["content-type"]


def test_new_form_renders(client):
    resp = client.get("/ui/workflows/new")
    assert resp.status_code == 200
    assert "Python script" in resp.text
    assert 'name="schedule_type"' in resp.text


def test_create_via_ui_form(client):
    resp = client.post(
        "/ui/workflows",
        data={
            "name": "ui-made",
            "description": "created from the UI",
            "script": "print('hi')",
            "schedule_type": "manual",
            "enabled": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/ui/workflows/")

    detail = client.get(location)
    assert detail.status_code == 200
    assert "ui-made" in detail.text
    assert "created from the UI" in detail.text


def test_create_via_ui_validation_error(client):
    # cron type without an expression should re-render the form with an error.
    resp = client.post(
        "/ui/workflows",
        data={
            "name": "bad-ui-cron",
            "script": "print('x')",
            "schedule_type": "cron",
            "enabled": "on",
        },
    )
    assert resp.status_code == 400
    assert "cron_expression is required" in resp.text


def test_edit_and_toggle_via_ui(client):
    create = client.post(
        "/ui/workflows",
        data={
            "name": "toggle-me",
            "script": "print('x')",
            "schedule_type": "manual",
            "enabled": "on",
        },
        follow_redirects=False,
    )
    wf_path = create.headers["location"]
    wf_id = wf_path.rsplit("/", 1)[1]

    # Toggle disables it.
    toggled = client.post(f"/ui/workflows/{wf_id}/toggle", follow_redirects=False)
    assert toggled.status_code == 303

    edit_page = client.get(f"/ui/workflows/{wf_id}/edit")
    assert edit_page.status_code == 200
    assert "toggle-me" in edit_page.text


def test_ui_requires_auth_when_key_set(monkeypatch, client):
    from app import web

    monkeypatch.setattr(web.settings, "api_key", "secret123")
    resp = client.get("/ui", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/ui/login"
