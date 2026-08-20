"""Job queue endpoints: submit, poll, list, cancel."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.exceptions import NotFoundError, PermissionDeniedError
from ...db.session import get_db
from ...models import Job, Role, User
from ...schemas.project import Page
from ...schemas.tools import JobOut, JobSubmitted
from ...services import projects as project_service
from ...tasks import queue as task_queue
from ...tasks.handlers import HANDLERS
from ..deps import get_current_user

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _visible(db: Session, user: User, job: Job) -> Job:
    if user.role == Role.ADMIN.value or job.user_id == user.id:
        return job
    if job.project_id and job.project_id in set(project_service.accessible_project_ids(db, user)):
        return job
    raise PermissionDeniedError("You do not have access to this job")


@router.get("/types", summary="Registered job types")
def job_types(_: User = Depends(get_current_user)) -> dict:
    return {"types": sorted(HANDLERS)}


@router.post("", response_model=JobSubmitted, status_code=202, summary="Submit a background job")
def submit_job(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobSubmitted:
    job_type = payload.get("type")
    params = payload.get("params") or {}
    project = None
    if payload.get("project_id"):
        project = project_service.get_project(db, payload["project_id"])
        project_service.require_access(db, project, user)
    job = task_queue.submit(db, job_type=job_type or "", params=params, user=user, project=project)
    return JobSubmitted(job_id=job.id, status=job.status, type=job.type)


@router.get("", response_model=Page[JobOut], summary="List your jobs")
def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    type_filter: str | None = Query(default=None, alias="type"),
    project_id: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Page[JobOut]:
    stmt = select(Job)
    if user.role != Role.ADMIN.value:
        accessible = list(project_service.accessible_project_ids(db, user))
        stmt = stmt.where((Job.user_id == user.id) | (Job.project_id.in_(accessible or [""])))
    if status_filter:
        stmt = stmt.where(Job.status == status_filter)
    if type_filter:
        stmt = stmt.where(Job.type == type_filter)
    if project_id:
        stmt = stmt.where(Job.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Job.created_at.desc()).offset((page - 1) * size).limit(size)).all()
    return Page[JobOut](
        items=[JobOut.model_validate(j) for j in rows],
        total=total,
        page=page,
        size=size,
        pages=max(1, (total + size - 1) // size),
    )


@router.get("/{job_id}", response_model=JobOut, summary="Poll a job")
def get_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> JobOut:
    job = db.get(Job, job_id)
    if not job:
        raise NotFoundError("Job not found")
    return JobOut.model_validate(_visible(db, user, job))


@router.post("/{job_id}/cancel", response_model=JobOut, summary="Cancel a pending job")
def cancel_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> JobOut:
    job = db.get(Job, job_id)
    if not job:
        raise NotFoundError("Job not found")
    _visible(db, user, job)
    return JobOut.model_validate(task_queue.cancel(db, job))


@router.delete("/{job_id}", status_code=204, summary="Delete a finished job record")
def delete_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    job = db.get(Job, job_id)
    if not job:
        raise NotFoundError("Job not found")
    _visible(db, user, job)
    db.delete(job)
    db.commit()
