"""Job queue abstraction.

* ``CELERY_BROKER_URL`` set  -> jobs are dispatched to Celery workers (production).
* otherwise                  -> an in-process thread pool runs them (single-node
  deployments, laptops and CI), with identical Job rows and API semantics.

Either way the ``jobs`` table is the contract the API and UI poll against, so the
frontend never needs to know which backend is active.
"""
from __future__ import annotations

import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.logging import get_logger
from ..db.base import utcnow
from ..db.session import SessionLocal
from ..models import Job, JobStatus, Project, User
from .handlers import get_handler

logger = get_logger("geneforge.tasks")

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=settings.task_local_workers, thread_name_prefix="geneforge-job"
            )
        return _executor


def run_job(job_id: str) -> None:
    """Execute a persisted job. Safe to call from a thread or a Celery worker."""
    db: Session = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            logger.warning("job %s vanished before execution", job_id)
            return
        if job.status not in (JobStatus.PENDING.value, JobStatus.RUNNING.value):
            return
        job.status = JobStatus.RUNNING.value
        job.started_at = utcnow()
        job.progress = 0.05
        db.commit()

        def progress(value: float, note: str | None = None) -> None:
            job.progress = max(0.0, min(1.0, float(value)))
            if note:
                job.params = {**(job.params or {}), "_stage": note}
            db.commit()

        try:
            handler = get_handler(job.type)
            result = handler(db, job.params or {}, progress)
            job.result = result
            job.status = JobStatus.SUCCEEDED.value
            job.progress = 1.0
            job.error = None
        except Exception as exc:  # noqa: BLE001 - persisted for the user to see
            logger.exception("job %s failed", job_id)
            job.status = JobStatus.FAILED.value
            job.error = f"{type(exc).__name__}: {exc}"
            job.result = {"traceback": traceback.format_exc()[-4000:]} if settings.debug else None
        finally:
            job.finished_at = utcnow()
            db.commit()
    finally:
        db.close()


def submit(
    db: Session,
    *,
    job_type: str,
    params: dict,
    user: User | None = None,
    project: Project | None = None,
) -> Job:
    """Create the Job row and dispatch it to the active backend."""
    get_handler(job_type)  # fail fast on unknown types
    job = Job(
        type=job_type,
        params=params,
        user_id=user.id if user else None,
        project_id=project.id if project else None,
        status=JobStatus.PENDING.value,
        backend="celery" if settings.queue_enabled else "local",
    )
    db.add(job)
    db.commit()

    if settings.queue_enabled:
        try:
            from .celery_app import execute_job

            async_result = execute_job.delay(job.id)
            job.external_id = getattr(async_result, "id", None)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - broker down: degrade to local
            logger.error("celery dispatch failed (%s); running locally", exc)
            job.backend = "local"
            db.commit()
            _get_executor().submit(run_job, job.id)
    else:
        _get_executor().submit(run_job, job.id)
    return job


def run_sync(db: Session, job_type: str, params: dict) -> dict:
    """Run a handler inline (small/interactive requests)."""
    handler = get_handler(job_type)
    return handler(db, params, lambda *_args, **_kwargs: None)


def cancel(db: Session, job: Job) -> Job:
    """Best-effort cancellation: pending jobs are marked cancelled."""
    if job.status == JobStatus.PENDING.value:
        job.status = JobStatus.CANCELLED.value
        job.finished_at = utcnow()
        db.commit()
    return job


def shutdown() -> None:
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None
