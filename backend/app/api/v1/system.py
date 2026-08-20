"""Health, readiness and platform capability endpoints."""
from __future__ import annotations

import platform
import time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ...bio.enzymes import ENZYMES
from ...core.config import settings
from ...db.session import get_db
from ...models import Job, JobStatus, Project, Sequence, User
from ..deps import get_current_user, require_admin

router = APIRouter(tags=["system"])
_STARTED = time.time()


@router.get("/health", summary="Liveness probe")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}


@router.get("/ready", summary="Readiness probe (checks the database)")
def ready(db: Session = Depends(get_db)) -> dict:
    checks = {"database": "ok"}
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc}"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks, "uptime_seconds": round(time.time() - _STARTED, 1)}


@router.get("/capabilities", summary="What this deployment supports")
def capabilities() -> dict:
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "import_formats": ["fasta", "genbank", "embl", "fastq", "snapgene(.dna)", "plain"],
        "export_formats": ["genbank", "fasta", "plain"],
        "enzyme_catalogue_size": len(ENZYMES),
        "queue_backend": "celery" if settings.queue_enabled else "local-threadpool",
        "registration_open": settings.allow_registration,
        "external_proxy_enabled": settings.external_proxy_enabled,
        "max_sequence_length": settings.max_sequence_length,
        "max_upload_bytes": settings.max_upload_bytes,
    }


@router.get("/stats", summary="Instance statistics (admin)")
def stats(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    def count(model) -> int:
        return db.scalar(select(func.count()).select_from(model)) or 0

    jobs_by_status = {
        row[0]: row[1]
        for row in db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)).all()
    }
    total_bp = db.scalar(select(func.coalesce(func.sum(Sequence.length), 0))) or 0
    return {
        "users": count(User),
        "projects": count(Project),
        "sequences": count(Sequence),
        "total_base_pairs": int(total_bp),
        "jobs": jobs_by_status,
        "pending_jobs": jobs_by_status.get(JobStatus.PENDING.value, 0),
        "python": platform.python_version(),
        "uptime_seconds": round(time.time() - _STARTED, 1),
    }


@router.get("/me/summary", summary="Dashboard summary for the current user")
def my_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    from ...services import projects as project_service

    project_ids = list(project_service.accessible_project_ids(db, user))
    sequences = db.scalar(
        select(func.count()).select_from(Sequence).where(Sequence.project_id.in_(project_ids or [""]))
    ) or 0
    recent = db.scalars(
        select(Sequence)
        .where(Sequence.project_id.in_(project_ids or [""]))
        .order_by(Sequence.updated_at.desc())
        .limit(8)
    ).all()
    running = db.scalar(
        select(func.count()).select_from(Job).where(
            Job.user_id == user.id, Job.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value])
        )
    ) or 0
    return {
        "projects": len(project_ids),
        "sequences": sequences,
        "active_jobs": running,
        "recent_sequences": [
            {
                "id": s.id,
                "name": s.name,
                "project_id": s.project_id,
                "length": s.length,
                "topology": s.topology,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in recent
        ],
    }
