"""FastAPI dependencies: authentication, RBAC and request metadata."""
from __future__ import annotations

import jwt
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..core.exceptions import AuthenticationError, PermissionDeniedError
from ..db.session import get_db
from ..models import Project, ProjectRole, Role, User
from ..services import projects as project_service
from ..services import users as user_service

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> User:
    """Authenticate via bearer JWT or X-API-Key header."""
    if x_api_key:
        user = user_service.resolve_api_key(db, x_api_key)
        if user:
            db.commit()
            request.state.user_id = user.id
            request.state.auth_method = "api_key"
            return user
        raise AuthenticationError("Invalid or expired API key")

    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Not authenticated")
    from ..core.security import decode_token

    try:
        claims = decode_token(credentials.credentials, expected_type="access")
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid access token") from exc

    user = db.get(User, claims.get("sub"))
    if user is None:
        raise AuthenticationError("User no longer exists")
    if not user.is_active:
        raise AuthenticationError("User account is disabled")
    request.state.user_id = user.id
    request.state.auth_method = "jwt"
    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> User | None:
    try:
        return get_current_user(request, db, credentials, x_api_key)
    except AuthenticationError:
        return None


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN.value:
        raise PermissionDeniedError("Administrator privileges required")
    return user


def require_editor(user: User = Depends(get_current_user)) -> User:
    if user.role == Role.VIEWER.value:
        raise PermissionDeniedError("Read-only account: editing is not permitted")
    return user


class ProjectAccess:
    """Dependency factory enforcing a minimum project role."""

    def __init__(self, minimum: str = ProjectRole.VIEWER.value):
        self.minimum = minimum

    def __call__(
        self,
        project_id: str,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> tuple[Project, User, str]:
        project = project_service.get_project(db, project_id)
        role = project_service.require_access(db, project, user, self.minimum)
        return project, user, role


project_viewer = ProjectAccess(ProjectRole.VIEWER.value)
project_editor = ProjectAccess(ProjectRole.EDITOR.value)
project_owner = ProjectAccess(ProjectRole.OWNER.value)


def client_meta(request: Request) -> dict:
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)
    return {"ip_address": ip, "user_agent": request.headers.get("user-agent")}
