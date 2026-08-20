"""Project CRUD and membership management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ...core.exceptions import NotFoundError
from ...db.session import get_db
from ...models import Project, ProjectRole, User
from ...schemas.project import (
    MemberAdd,
    MemberOut,
    Page,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectUpdate,
)
from ...services import audit
from ...services import projects as project_service
from ...services import users as user_service
from ..deps import client_meta, get_current_user, project_owner, project_viewer, require_editor

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_out(project: Project, role: str | None, count: int = 0) -> ProjectOut:
    data = ProjectOut.model_validate(project)
    data.my_role = role
    data.sequence_count = count
    return data


@router.get("", response_model=Page[ProjectOut], summary="List projects you can access")
def list_projects(
    search: str | None = None,
    include_archived: bool = False,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Page[ProjectOut]:
    rows, total, roles, counts = project_service.list_projects(
        db, user, search=search, include_archived=include_archived, page=page, size=size
    )
    return Page[ProjectOut](
        items=[_to_out(p, roles.get(p.id), counts.get(p.id, 0)) for p in rows],
        total=total,
        page=page,
        size=size,
        pages=max(1, (total + size - 1) // size),
    )


@router.post("", response_model=ProjectDetail, status_code=201, summary="Create a project")
def create_project(
    payload: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor),
) -> ProjectDetail:
    project = project_service.create_project(
        db,
        user,
        name=payload.name,
        description=payload.description,
        tags=payload.tags,
        metadata=payload.metadata,
    )
    audit.record(
        db, action="project.create", user_id=user.id, entity_type="project", entity_id=project.id,
        detail={"name": project.name}, **client_meta(request),
    )
    db.commit()
    detail = ProjectDetail.model_validate(project)
    detail.my_role = ProjectRole.OWNER.value
    detail.members = [MemberOut(**m) for m in project_service.members_with_users(db, project)]
    detail.metadata = project.metadata_json or {}
    return detail


@router.get("/{project_id}", response_model=ProjectDetail, summary="Project detail")
def get_project(
    access: tuple[Project, User, str] = Depends(project_viewer),
    db: Session = Depends(get_db),
) -> ProjectDetail:
    project, _, role = access
    detail = ProjectDetail.model_validate(project)
    detail.my_role = role
    detail.members = [MemberOut(**m) for m in project_service.members_with_users(db, project)]
    detail.metadata = project.metadata_json or {}
    from ...services import sequences as sequence_service

    _, total, _ = sequence_service.list_sequences(db, project.id, size=1)
    detail.sequence_count = total
    return detail


@router.patch("/{project_id}", response_model=ProjectOut, summary="Update a project")
def update_project(
    payload: ProjectUpdate,
    request: Request,
    access: tuple[Project, User, str] = Depends(project_owner),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project, user, role = access
    project_service.update_project(db, project, **payload.model_dump(exclude_none=True))
    audit.record(
        db, action="project.update", user_id=user.id, entity_type="project", entity_id=project.id,
        detail=payload.model_dump(exclude_none=True), **client_meta(request),
    )
    db.commit()
    return _to_out(project, role)


@router.delete("/{project_id}", status_code=204, summary="Delete a project and its sequences")
def delete_project(
    request: Request,
    access: tuple[Project, User, str] = Depends(project_owner),
    db: Session = Depends(get_db),
) -> None:
    project, user, _ = access
    audit.record(
        db, action="project.delete", user_id=user.id, entity_type="project", entity_id=project.id,
        detail={"name": project.name}, **client_meta(request),
    )
    project_service.delete_project(db, project)
    db.commit()


@router.get("/{project_id}/members", response_model=list[MemberOut], summary="List project members")
def list_members(
    access: tuple[Project, User, str] = Depends(project_viewer),
    db: Session = Depends(get_db),
) -> list[MemberOut]:
    project, _, _ = access
    return [MemberOut(**m) for m in project_service.members_with_users(db, project)]


@router.post("/{project_id}/members", response_model=MemberOut, status_code=201, summary="Add or update a member")
def add_member(
    payload: MemberAdd,
    request: Request,
    access: tuple[Project, User, str] = Depends(project_owner),
    db: Session = Depends(get_db),
) -> MemberOut:
    project, actor, _ = access
    target: User | None = None
    if payload.user_id:
        target = db.get(User, payload.user_id)
    elif payload.username or payload.email:
        target = user_service.find_by_login(db, payload.username or payload.email or "")
    if not target:
        raise NotFoundError("Target user not found")
    member = project_service.add_member(db, project, target, payload.role)
    audit.record(
        db, action="project.member_add", user_id=actor.id, entity_type="project", entity_id=project.id,
        detail={"member": target.username, "role": payload.role}, **client_meta(request),
    )
    db.commit()
    return MemberOut(id=member.id, user_id=target.id, role=member.role, username=target.username, email=target.email)


@router.delete("/{project_id}/members/{user_id}", status_code=204, summary="Remove a member")
def remove_member(
    user_id: str,
    request: Request,
    access: tuple[Project, User, str] = Depends(project_owner),
    db: Session = Depends(get_db),
) -> None:
    project, actor, _ = access
    project_service.remove_member(db, project, user_id)
    audit.record(
        db, action="project.member_remove", user_id=actor.id, entity_type="project", entity_id=project.id,
        detail={"member_id": user_id}, **client_meta(request),
    )
    db.commit()
