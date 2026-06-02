"""Application configuration loaded from environment variables.

On Azure App Service these are set as Application Settings; locally they can be
placed in a `.env` file (see `.env.example`).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Database -----------------------------------------------------------
    # Standard SQLAlchemy URL, e.g.
    #   postgresql+psycopg2://user:pass@host:5432/dbname?sslmode=require
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/workflow"

    # --- API ----------------------------------------------------------------
    api_title: str = "Workflow Engine"
    api_description: str = "Schedule and execute Python workflows."
    # Simple shared-secret API key. Requests must send `X-API-Key: <key>`.
    # Leave empty to disable auth (NOT recommended outside local dev).
    api_key: str = ""

    # --- Execution ----------------------------------------------------------
    # Python interpreter used to run workflow scripts.
    python_executable: str = "python"
    # Default per-run wall-clock timeout (seconds) if a workflow doesn't set one.
    default_timeout_seconds: int = 3600
    # Directory where transient script files / working dirs are created.
    work_dir: str = "/tmp/workflow-runs"
    # Maximum number of workflows that may execute concurrently.
    max_concurrent_jobs: int = 5

    # --- Scheduler ----------------------------------------------------------
    timezone: str = "UTC"

    @property
    def jobstore_url(self) -> str:
        """APScheduler's SQLAlchemyJobStore wants a plain sync URL."""
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
