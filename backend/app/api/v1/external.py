"""External database/API registry endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ...bio import seqio
from ...core.config import settings
from ...core.exceptions import ValidationError
from ...db.session import get_db
from ...models import ProjectRole, User
from ...schemas.tools import (
    ExternalFetchRequest,
    ExternalResourceCreate,
    ExternalResourceOut,
    ExternalResourceUpdate,
)
from ...services import audit
from ...services import external as external_service
from ...services import projects as project_service
from ...services import sequences as sequence_service
from ..deps import client_meta, get_current_user, require_admin

router = APIRouter(prefix="/external", tags=["external"])


@router.get("/resources", response_model=list[ExternalResourceOut], summary="List configured external resources")
def list_resources(
    enabled_only: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ExternalResourceOut]:
    return [ExternalResourceOut.model_validate(r) for r in external_service.list_resources(db, enabled_only=enabled_only)]


@router.post("/resources", response_model=ExternalResourceOut, status_code=201, summary="Register a resource (admin)")
def create_resource(
    payload: ExternalResourceCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ExternalResourceOut:
    from ...models import ExternalResource

    row = ExternalResource(**payload.model_dump(), created_by_id=admin.id)
    db.add(row)
    audit.record(
        db, action="external.create", user_id=admin.id, entity_type="external_resource",
        entity_id=row.id, detail={"name": row.name}, **client_meta(request),
    )
    db.commit()
    db.refresh(row)
    return ExternalResourceOut.model_validate(row)


@router.patch("/resources/{resource_id}", response_model=ExternalResourceOut, summary="Update a resource (admin)")
def update_resource(
    resource_id: str,
    payload: ExternalResourceUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ExternalResourceOut:
    row = external_service.get_resource(db, resource_id)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return ExternalResourceOut.model_validate(row)


@router.delete("/resources/{resource_id}", status_code=204, summary="Delete a resource (admin)")
def delete_resource(
    resource_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    row = external_service.get_resource(db, resource_id)
    db.delete(row)
    db.commit()


@router.post("/resources/seed", summary="Seed the default resource set (admin)")
def seed_resources(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    created = external_service.seed_defaults(db, created_by=admin)
    db.commit()
    return {"created": created}


@router.post("/resources/{resource_id}/url", summary="Render a resource link without calling it")
def render_resource_url(
    resource_id: str,
    payload: ExternalFetchRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    row = external_service.get_resource(db, resource_id)
    return {"url": external_service.render_url(row, payload.params), "kind": row.kind}


@router.post("/resources/{resource_id}/fetch", summary="Fetch a record server-side (optionally importing it)")
def fetch_resource(
    resource_id: str,
    payload: ExternalFetchRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    row = external_service.get_resource(db, resource_id)
    text, url = external_service.fetch(row, payload.params)
    detected = seqio.detect_format(text, None)
    result: dict = {
        "resource": row.name,
        "url": url,
        "detected_format": detected,
        "bytes": len(text),
        "preview": text[:2000],
        "imported": [],
    }
    if payload.import_to_project:
        project = project_service.get_project(db, payload.import_to_project)
        project_service.require_access(db, project, user, ProjectRole.EDITOR.value)
        try:
            records = seqio.parse_any(text, f"{row.name}.{ 'gb' if detected == 'genbank' else 'fasta' }")
        except seqio.SequenceParseError as exc:
            raise ValidationError(f"Fetched payload could not be parsed: {exc}") from exc
        for rec in records:
            stored = sequence_service.create_from_record(
                db, project, user, rec, auto_annotate=payload.auto_annotate
            )
            result["imported"].append(
                {"sequence_id": stored.id, "name": stored.name, "length": stored.length}
            )
        audit.record(
            db, action="external.import", user_id=user.id, entity_type="project", entity_id=project.id,
            detail={"resource": row.name, "url": url, "count": len(result["imported"])}, **client_meta(request),
        )
        db.commit()
    return result


@router.get("/proxy-policy", summary="Effective proxy policy")
def proxy_policy(_: User = Depends(get_current_user)) -> dict:
    return {
        "enabled": settings.external_proxy_enabled,
        "allowlist": settings.external_proxy_allowlist,
        "timeout_seconds": settings.external_proxy_timeout_seconds,
    }
