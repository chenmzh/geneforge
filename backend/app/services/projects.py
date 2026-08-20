"""Project service: CRUD, membership and the single source of truth for access."""
from __future__ import annotations

import re
from collections.abc import Sequence as Seq

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from ..models import Project, ProjectMember, ProjectRole, Role, Sequence, User

_ROLE_RANK = {ProjectRole.VIEWER.value: 1, ProjectRole.EDITOR.value: 2, ProjectRole.OWNER.value: 3}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "project"


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug = base
    n = 2
    while db.scalars(select(Project).where(Project.slug == slug)).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


def create_project(
    db: Session,
    owner: User,
    *,
    name: str,
    description: str | None = None,
    tags: list | None = None,
    metadata: dict | None = None,
) -> Project:
    project = Project(
        name=name,
        slug=unique_slug(db, name),
        description=description,
        owner_id=owner.id,
        tags=tags or [],
        metadata_json=metadata or {},
    )
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=owner.id, role=ProjectRole.OWNER.value))
    db.flush()
    return project


def get_project(db: Session, project_id: str) -> Project:
    stmt = select(Project).options(selectinload(Project.members)).where(
        (Project.id == project_id) | (Project.slug == project_id)
    )
    project = db.scalars(stmt).first()
    if not project:
        raise NotFoundError("Project not found")
    return project


def member_role(db: Session, project: Project, user: User) -> str | None:
    if user.role == Role.ADMIN.value:
        return ProjectRole.OWNER.value
    if project.owner_id == user.id:
        return ProjectRole.OWNER.value
    membership = db.scalars(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user.id
        )
    ).first()
    return membership.role if membership else None


def require_access(db: Session, project: Project, user: User, minimum: str = ProjectRole.VIEWER.value) -> str:
    role = member_role(db, project, user)
    if role is None or _ROLE_RANK.get(role, 0) < _ROLE_RANK[minimum]:
        raise PermissionDeniedError(f"Requires project role '{minimum}' or higher")
    return role


def list_projects(
    db: Session,
    user: User,
    *,
    search: str | None = None,
    include_archived: bool = False,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Project], int, dict[str, str], dict[str, int]]:
    stmt = select(Project)
    if user.role != Role.ADMIN.value:
        member_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
        stmt = stmt.where((Project.owner_id == user.id) | (Project.id.in_(member_ids)))
    if not include_archived:
        stmt = stmt.where(Project.is_archived.is_(False))
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(func.lower(Project.name).like(like) | func.lower(Project.slug).like(like))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(stmt.order_by(Project.updated_at.desc()).offset((page - 1) * size).limit(size))
    )
    roles = {p.id: member_role(db, p, user) or ProjectRole.VIEWER.value for p in rows}
    counts_stmt = (
        select(Sequence.project_id, func.count(Sequence.id))
        .where(Sequence.project_id.in_([p.id for p in rows] or [""]))
        .group_by(Sequence.project_id)
    )
    counts = dict(db.execute(counts_stmt).all())
    return rows, total, roles, counts


def update_project(db: Session, project: Project, **changes) -> Project:
    for key, value in changes.items():
        if value is None:
            continue
        if key == "metadata":
            project.metadata_json = value
        elif hasattr(project, key):
            setattr(project, key, value)
    db.flush()
    return project


def delete_project(db: Session, project: Project) -> None:
    db.delete(project)
    db.flush()


def add_member(db: Session, project: Project, user: User, role: str) -> ProjectMember:
    existing = db.scalars(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user.id
        )
    ).first()
    if existing:
        existing.role = role
        db.flush()
        return existing
    if role not in _ROLE_RANK:
        raise ConflictError(f"Unknown project role: {role}")
    member = ProjectMember(project_id=project.id, user_id=user.id, role=role)
    db.add(member)
    db.flush()
    return member


def remove_member(db: Session, project: Project, user_id: str) -> None:
    if project.owner_id == user_id:
        raise ConflictError("Cannot remove the project owner")
    member = db.scalars(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user_id
        )
    ).first()
    if not member:
        raise NotFoundError("Membership not found")
    db.delete(member)
    db.flush()


def members_with_users(db: Session, project: Project) -> list[dict]:
    rows = db.execute(
        select(ProjectMember, User).join(User, User.id == ProjectMember.user_id).where(
            ProjectMember.project_id == project.id
        )
    ).all()
    return [
        {
            "id": m.id,
            "user_id": m.user_id,
            "role": m.role,
            "username": u.username,
            "email": u.email,
        }
        for m, u in rows
    ]


def accessible_project_ids(db: Session, user: User) -> Seq[str]:
    if user.role == Role.ADMIN.value:
        return [p for (p,) in db.execute(select(Project.id)).all()]
    member_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    rows = db.execute(select(Project.id).where((Project.owner_id == user.id) | (Project.id.in_(member_ids)))).all()
    return [p for (p,) in rows]
