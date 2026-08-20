"""Celery application. Only imported when CELERY_BROKER_URL is configured.

Start a worker with:
    celery -A app.tasks.celery_app:celery_app worker --loglevel=info
"""
from __future__ import annotations

from celery import Celery

from ..core.config import settings

celery_app = Celery(
    "geneforge",
    broker=settings.celery_broker_url or "memory://",
    backend=settings.celery_result_backend or settings.celery_broker_url or "cache+memory://",
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=settings.task_max_runtime_seconds,
    task_soft_time_limit=max(30, settings.task_max_runtime_seconds - 30),
    broker_connection_retry_on_startup=True,
)


@celery_app.task(name="geneforge.execute_job", bind=True)
def execute_job(self, job_id: str) -> str:  # pragma: no cover - runs in worker
    from .queue import run_job

    run_job(job_id)
    return job_id
