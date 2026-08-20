"""User administration and audit log (admin only, except /users/me updates)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from ...core.exceptions import ValidationError
from ...db.session import get_db
from ...models import AuditLog, Role, User
from ...schemas.auth import AuditLogOut, UserCreate, UserOut, UserUpdate
from ...schemas.project import Page
from ...services import audit
from ...services import users as user_service
from ..deps import client_meta, get_current_user, require_admin

router = APIRouter(tags=["users"])


@router.get("/users", response_model=Page[UserOut], summary="List users (admin)")
def list_users(
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Page[UserOut]:
    stmt = select(User)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.username).like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(User.created_at.desc()).offset((page - 1) * size).limit(size)).all()
    return Page[UserOut](
        items=[UserOut.model_validate(u) for u in rows],
        total=total,
        page=page,
        size=size,
        pages=max(1, (total + size - 1) // size),
    )


@router.post("/users", response_model=UserOut, status_code=201, summary="Create a user (admin)")
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserOut:
    user = user_service.create_user(
        db,
        email=str(payload.email),
        username=payload.username,
        password=payload.password,
        full_name=payload.full_name,
        role=payload.role or Role.EDITOR.value,
    )
    audit.record(db, action="user.create", user_id=admin.id, entity_type="user", entity_id=user.id, **client_meta(request))
    db.commit()
    return UserOut.model_validate(user)


@router.patch("/users/me", response_model=UserOut, summary="Update your own profile")
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserOut:
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.settings is not None:
        user.settings_json = payload.settings
    if payload.role is not None or payload.is_active is not None:
        raise ValidationError("Only administrators may change role or activation")
    db.commit()
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserOut, summary="Update a user (admin)")
def update_user(
    user_id: str,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserOut:
    user = user_service.get_by_id(db, user_id)
    if payload.role is not None:
        if payload.role not in {r.value for r in Role}:
            raise ValidationError(f"Unknown role: {payload.role}")
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.email is not None:
        user.email = str(payload.email).lower()
    audit.record(
        db, action="user.update", user_id=admin.id, entity_type="user", entity_id=user.id,
        detail=payload.model_dump(exclude_none=True), **client_meta(request),
    )
    db.commit()
    return UserOut.model_validate(user)


@router.delete("/users/{user_id}", status_code=204, summary="Deactivate a user (admin)")
def deactivate_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    user = user_service.get_by_id(db, user_id)
    if user.id == admin.id:
        raise ValidationError("You cannot deactivate your own account")
    user.is_active = False
    audit.record(db, action="user.deactivate", user_id=admin.id, entity_type="user", entity_id=user.id, **client_meta(request))
    db.commit()


@router.get("/audit-logs", response_model=Page[AuditLogOut], summary="Query the audit trail (admin)")
def audit_logs(
    action: str | None = None,
    entity_id: str | None = None,
    user_id: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Page[AuditLogOut]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(desc(AuditLog.created_at)).offset((page - 1) * size).limit(size)).all()
    return Page[AuditLogOut](
        items=[AuditLogOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=max(1, (total + size - 1) // size),
    )
