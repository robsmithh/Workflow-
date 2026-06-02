"""Gunicorn configuration for Azure App Service.

We intentionally run a SINGLE worker. The in-process APScheduler must have
exactly one instance against the shared Postgres jobstore; multiple workers
would each start a scheduler and double-fire jobs. Scale execution via
MAX_CONCURRENT_JOBS (the scheduler's thread pool), not by adding workers.
"""
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = 1
worker_class = "uvicorn.workers.UvicornWorker"
timeout = int(os.getenv("GUNICORN_TIMEOUT", "600"))
keepalive = 5
accesslog = "-"
errorlog = "-"
