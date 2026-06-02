"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.base import STATE_STOPPED
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import web
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.routers import runs, workflows
from app.scheduler import get_scheduler, reset_scheduler, sync_workflow_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()


def _sync_all_jobs() -> None:
    """Reconcile scheduler jobs with the workflows in the database on startup."""
    from app.crud import list_workflows

    db = SessionLocal()
    try:
        for workflow in list_workflows(db, limit=10_000):
            try:
                sync_workflow_job(workflow)
            except Exception:
                logger.exception("Failed to schedule workflow %s", workflow.id)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables if they don't exist. For real migrations use Alembic.
    Base.metadata.create_all(bind=engine)

    scheduler = get_scheduler()
    if scheduler.state == STATE_STOPPED:
        scheduler.start()
    _sync_all_jobs()
    logger.info("Scheduler started")

    yield

    if scheduler.state != STATE_STOPPED:
        scheduler.shutdown(wait=False)
    reset_scheduler()
    logger.info("Scheduler stopped")


app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version="0.1.0",
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(workflows.router)
app.include_router(runs.router)
app.include_router(web.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui")
