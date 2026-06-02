"""Workflow execution engine.

Each workflow's Python source is written to a temporary file and run in a
separate subprocess with a wall-clock timeout. stdout/stderr and the exit code
are captured into a `WorkflowRun` row.

NOTE: workflow scripts run with the same OS privileges as this service. Only
allow trusted users to create/edit workflows, and consider running the app
under a low-privilege account. See README for hardening notes.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone

from app.config import get_settings
from app.database import SessionLocal
from app.models import RunStatus, TriggerType, Workflow, WorkflowRun

logger = logging.getLogger(__name__)
settings = get_settings()

# Cap how much output we persist to avoid unbounded rows.
_MAX_OUTPUT_CHARS = 1_000_000


def _truncate(text: str) -> str:
    if len(text) > _MAX_OUTPUT_CHARS:
        return text[:_MAX_OUTPUT_CHARS] + "\n...[truncated]..."
    return text


def execute_workflow_job(
    workflow_id: int, trigger: str = TriggerType.scheduled.value
) -> None:
    """Entry point invoked by APScheduler (and by the manual-run endpoint).

    Opens its own DB session so it is independent of any request lifecycle.
    """
    db = SessionLocal()
    run: WorkflowRun | None = None
    try:
        workflow = db.get(Workflow, workflow_id)
        if workflow is None:
            logger.warning("Workflow %s no longer exists; skipping run", workflow_id)
            return

        run = WorkflowRun(
            workflow_id=workflow.id,
            status=RunStatus.running,
            trigger=TriggerType(trigger),
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        timeout = workflow.timeout_seconds or settings.default_timeout_seconds
        _run_script(workflow.script, timeout, run)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Unexpected error executing workflow %s", workflow_id)
        if run is not None:
            run.status = RunStatus.failed
            run.finished_at = datetime.now(timezone.utc)
            run.stderr = (run.stderr or "") + "\n[internal executor error]"
    finally:
        if run is not None:
            db.add(run)
            db.commit()
        db.close()


def _run_script(script: str, timeout: int, run: WorkflowRun) -> None:
    os.makedirs(settings.work_dir, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="wf-", dir=settings.work_dir)
    script_path = os.path.join(workdir, "workflow.py")
    with open(script_path, "w", encoding="utf-8") as fh:
        fh.write(script)

    try:
        proc = subprocess.run(
            [settings.python_executable, script_path],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        run.exit_code = proc.returncode
        run.stdout = _truncate(proc.stdout or "")
        run.stderr = _truncate(proc.stderr or "")
        run.status = RunStatus.success if proc.returncode == 0 else RunStatus.failed
    except subprocess.TimeoutExpired as exc:
        run.status = RunStatus.timeout
        run.stdout = _truncate(exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""))
        run.stderr = (
            _truncate(exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or ""))
            + f"\n[timed out after {timeout}s]"
        )
    finally:
        run.finished_at = datetime.now(timezone.utc)
