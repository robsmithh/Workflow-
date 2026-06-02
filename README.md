# Workflow Engine

A lightweight FastAPI service for **scheduling and executing Python workflows** —
a self-hosted alternative to Alteryx Server for the "run this code on a schedule"
use case. Built to deploy on **Azure App Service** with a **PostgreSQL** backend.

- Define workflows (a name + Python script + schedule) over a REST API.
- Schedule them with cron, fixed intervals, or a one-shot date — or trigger manually.
- Each execution runs in an isolated subprocess with a timeout; stdout/stderr,
  exit code, and timing are captured as a **run** record.
- Scheduling is backed by [APScheduler](https://apscheduler.readthedocs.io/) with a
  Postgres jobstore, so schedules survive restarts.

> Status: MVP. Single-task workflows (one script per workflow). Multi-step DAGs
> are a planned extension — see [Roadmap](#roadmap).

## Architecture

```
FastAPI (app/main.py)
 ├── routers/workflows.py   CRUD + manual run + run history
 ├── routers/runs.py        inspect individual runs
 ├── scheduler.py           APScheduler (AsyncIOScheduler + Postgres jobstore)
 ├── executor.py            runs a workflow's script in a subprocess, records a run
 ├── models.py              Workflow, WorkflowRun (SQLAlchemy)
 └── database.py            sync SQLAlchemy engine/session
PostgreSQL                  app tables + APScheduler jobstore (apscheduler_jobs)
```

When a workflow is created/updated, its schedule is reconciled into APScheduler.
When the scheduler fires (or you POST `/run`), `execute_workflow_job` writes the
script to a temp file, runs it with the configured Python interpreter, and stores
the outcome in `workflow_runs`.

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # point DATABASE_URL at your Postgres (or use SQLite for a quick spin)
alembic upgrade head          # create tables
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for the interactive API.

### Create and run a workflow

```bash
# Create a workflow that runs every minute
curl -X POST localhost:8000/workflows -H 'content-type: application/json' -d '{
  "name": "etl-nightly",
  "description": "Pulls data and prints a summary",
  "script": "print(\"running ETL...\")\nprint(\"done\")",
  "schedule_type": "cron",
  "cron_expression": "0 2 * * *",
  "timeout_seconds": 1800
}'

# Trigger it immediately (runs synchronously, returns the run record)
curl -X POST localhost:8000/workflows/1/run

# View run history
curl localhost:8000/workflows/1/runs
```

### Schedule types

| `schedule_type` | Required field      | Example                         |
|-----------------|---------------------|---------------------------------|
| `manual`        | —                   | run only via `POST /run`        |
| `cron`          | `cron_expression`   | `"0 2 * * *"` (2am daily)       |
| `interval`      | `interval_seconds`  | `3600` (hourly)                 |
| `date`          | `run_at`            | `"2026-07-01T09:00:00Z"`        |

## API

| Method | Path                         | Description                          |
|--------|------------------------------|--------------------------------------|
| POST   | `/workflows`                 | Create a workflow                    |
| GET    | `/workflows`                 | List workflows (with `next_run_time`)|
| GET    | `/workflows/{id}`            | Get one workflow                     |
| PATCH  | `/workflows/{id}`            | Update (partial); re-syncs schedule  |
| DELETE | `/workflows/{id}`            | Delete workflow + its schedule       |
| POST   | `/workflows/{id}/run`        | Run now (synchronous)                |
| GET    | `/workflows/{id}/runs`       | Run history                          |
| GET    | `/runs/{id}`                 | Single run detail                    |
| GET    | `/health`                    | Health check                         |

### Auth

Set `API_KEY` to require an `X-API-Key: <key>` header on all `/workflows` and
`/runs` endpoints. Empty `API_KEY` disables auth (local dev only).

## Deploying to Azure App Service

1. **Provision Postgres** (Azure Database for PostgreSQL Flexible Server). Note the
   connection string; append `?sslmode=require`.
2. **Create the App Service** (Linux, Python 3.12 or a container).
3. **Application settings** (env vars): set `DATABASE_URL`, `API_KEY`, and any
   execution overrides. Set **`WEBSITES_PORT=8000`** if using the container.
4. **Always On**: enable it (Configuration → General settings) so the scheduler
   keeps running between requests.
5. **Single instance / single worker**: keep the App Service plan at **1 instance**
   and the app at **1 process**. The bundled `gunicorn_conf.py` already pins
   `workers = 1`. This is required — APScheduler runs in-process, and multiple
   schedulers against one jobstore would double-fire jobs. Scale concurrency with
   `MAX_CONCURRENT_JOBS`, not extra workers/instances.
6. **Startup command**: `startup.sh` (runs `alembic upgrade head`, then gunicorn).

### Container option

```bash
docker build -t workflow-engine .
docker run -p 8000:8000 -e DATABASE_URL=... -e API_KEY=... workflow-engine
```

## Configuration

| Env var                   | Default                  | Purpose                                  |
|---------------------------|--------------------------|------------------------------------------|
| `DATABASE_URL`            | local postgres           | SQLAlchemy URL (app + jobstore)          |
| `API_KEY`                 | `""` (auth off)          | Shared secret for `X-API-Key`            |
| `PYTHON_EXECUTABLE`       | `python`                 | Interpreter used to run scripts          |
| `DEFAULT_TIMEOUT_SECONDS` | `3600`                   | Fallback per-run timeout                 |
| `WORK_DIR`                | `/tmp/workflow-runs`     | Temp dir for script files                |
| `MAX_CONCURRENT_JOBS`     | `5`                      | Scheduler thread-pool size               |
| `TIMEZONE`                | `UTC`                    | Scheduler timezone                       |

## Security notes

Workflow scripts execute **arbitrary Python with the same privileges as the
service**. This is fine for a trusted internal team but is not a sandbox.

- Keep `API_KEY` set and restrict who can create/edit workflows.
- Run the app as a low-privilege OS user.
- For untrusted code, run executions in isolated containers/VMs (a future
  executor backend) rather than local subprocesses.

## Tests

```bash
pip install pytest httpx
pytest
```

Tests use a temporary SQLite database and exercise the full request → execute →
record path.

## Roadmap

- Multi-step workflows / DAGs with inter-step dependencies.
- Pluggable execution backends (container/VM isolation).
- Notifications on failure (email/webhook) and retry policies.
- Web UI for managing workflows and browsing run logs.
