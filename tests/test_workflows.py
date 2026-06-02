"""Smoke tests for the workflow API and execution engine."""


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_and_run_workflow(client):
    payload = {
        "name": "hello",
        "description": "prints hello",
        "script": "print('hello from workflow')",
        "schedule_type": "manual",
    }
    resp = client.post("/workflows", json=payload)
    assert resp.status_code == 201, resp.text
    workflow = resp.json()
    assert workflow["name"] == "hello"
    workflow_id = workflow["id"]

    # Manual trigger executes synchronously and returns the run record.
    resp = client.post(f"/workflows/{workflow_id}/run")
    assert resp.status_code == 200, resp.text
    run = resp.json()
    assert run["status"] == "success"
    assert run["exit_code"] == 0
    assert "hello from workflow" in run["stdout"]
    assert run["trigger"] == "manual"


def test_failing_workflow_records_failure(client):
    payload = {
        "name": "boom",
        "script": "raise SystemExit(3)",
        "schedule_type": "manual",
    }
    resp = client.post("/workflows", json=payload)
    assert resp.status_code == 201, resp.text
    workflow_id = resp.json()["id"]

    run = client.post(f"/workflows/{workflow_id}/run").json()
    assert run["status"] == "failed"
    assert run["exit_code"] == 3


def test_cron_requires_expression(client):
    payload = {
        "name": "bad-cron",
        "script": "print('x')",
        "schedule_type": "cron",
    }
    resp = client.post("/workflows", json=payload)
    assert resp.status_code == 422


def test_duplicate_name_conflict(client):
    payload = {"name": "dupe", "script": "print(1)", "schedule_type": "manual"}
    assert client.post("/workflows", json=payload).status_code == 201
    assert client.post("/workflows", json=payload).status_code == 409


def test_cron_workflow_schedules_next_run(client):
    payload = {
        "name": "nightly",
        "script": "print('nightly')",
        "schedule_type": "cron",
        "cron_expression": "0 2 * * *",
    }
    resp = client.post("/workflows", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["next_run_time"] is not None
