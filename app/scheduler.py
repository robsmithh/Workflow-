"""APScheduler integration.

Uses an AsyncIOScheduler with a Postgres-backed SQLAlchemyJobStore so scheduled
jobs survive restarts. Job IDs map 1:1 to workflows (`workflow:<id>`).

IMPORTANT: run a single scheduler instance. On Azure App Service that means a
single always-on instance with one worker process (see README). Running
multiple processes against the same jobstore can double-fire jobs.
"""
from __future__ import annotations

import logging

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.models import ScheduleType, Workflow

logger = logging.getLogger(__name__)
settings = get_settings()

_scheduler: AsyncIOScheduler | None = None


def job_id(workflow_id: int) -> str:
    return f"workflow:{workflow_id}"


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            jobstores={
                "default": SQLAlchemyJobStore(url=settings.jobstore_url)
            },
            executors={"default": ThreadPoolExecutor(settings.max_concurrent_jobs)},
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
            timezone=settings.timezone,
        )
    return _scheduler


def _build_trigger(workflow: Workflow):
    if workflow.schedule_type == ScheduleType.cron:
        return CronTrigger.from_crontab(
            workflow.cron_expression, timezone=settings.timezone
        )
    if workflow.schedule_type == ScheduleType.interval:
        return IntervalTrigger(
            seconds=workflow.interval_seconds, timezone=settings.timezone
        )
    if workflow.schedule_type == ScheduleType.date:
        return DateTrigger(run_date=workflow.run_at, timezone=settings.timezone)
    return None  # manual


def sync_workflow_job(workflow: Workflow) -> None:
    """Create/update/remove the scheduled job to match the workflow state."""
    scheduler = get_scheduler()
    jid = job_id(workflow.id)

    trigger = _build_trigger(workflow) if workflow.enabled else None
    if trigger is None:
        remove_workflow_job(workflow.id)
        return

    scheduler.add_job(
        func="app.executor:execute_workflow_job",
        trigger=trigger,
        args=[workflow.id],
        id=jid,
        name=workflow.name,
        replace_existing=True,
    )
    logger.info("Scheduled job %s (%s)", jid, workflow.schedule_type.value)


def remove_workflow_job(workflow_id: int) -> None:
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id(workflow_id))
        logger.info("Removed job %s", job_id(workflow_id))
    except Exception:
        # Job may not exist; that's fine.
        pass


def get_next_run_time(workflow_id: int):
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id(workflow_id))
    return job.next_run_time if job else None


def reset_scheduler() -> None:
    """Drop the singleton so the next get_scheduler() builds a fresh instance.

    Used after shutdown (notably between tests) since APScheduler instances are
    not designed to be restarted once shut down.
    """
    global _scheduler
    _scheduler = None
