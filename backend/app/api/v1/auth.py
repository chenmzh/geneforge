"""Authentication and account endpoints."""
from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.exceptions import AuthenticationError, PermissionDeniedError
from ...core.security import create_access_token, create_refresh_token, decode_token
from ...db.session import get_db
from ...models import Role, User
from ...schemas.auth import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    LoginRequest,
    PasswordChange,
    RefreshRequest,
    Token,
    UserCreate,
    UserOut,
)
from ...services import audit
from ...services import users as user_service
from ..deps import client_meta, get_current_user

router = APIRouter(tags=["auth"])


def _tokens(user: User) -> Token:
    claims = {"role": user.role, "username": user.username}
    return Token(
        access_token=create_access_token(user.id, **claims),
        refresh_token=create_refresh_token(user.id, **claims),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/auth/register", response_model=UserOut, status_code=201, summary="Register a new account")
def register(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> UserOut:
    if not settings.allow_registration:
        raise PermissionDeniedError("Self-registration is disabled; ask an administrator for an account")
    role = Role.EDITOR.value
    if payload.role and payload.role != Role.EDITOR.value:
        raise PermissionDeniedError("Only administrators may assign roles")
    user = user_service.create_user(
        db,
        email=str(payload.email),
        username=payload.username,
        password=payload.password,
        full_name=payload.full_name,
        role=role,
    )
    audit.record(db, action="user.register", user_id=user.id, entity_type="user", entity_id=user.id, **client_meta(request))
    db.commit()
    return UserOut.model_validate(user)


@router.post("/auth/login", response_model=Token, summary="Exchange credentials for JWT tokens")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> Token:
    user = user_service.authenticate(db, payload.username, payload.password)
    audit.record(db, action="user.login", user_id=user.id, entity_type="user", entity_id=user.id, **client_meta(request))
    db.commit()
    return _tokens(user)


@router.post("/auth/refresh", response_model=Token, summary="Rotate an expired access token")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> Token:
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Refresh token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid refresh token") from exc
    user = db.get(User, claims.get("sub"))
    if not user or not user.is_active:
        raise AuthenticationError("User no longer active")
    return _tokens(user)


@router.get("/auth/me", response_model=UserOut, summary="Current authenticated user")
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/auth/change-password", status_code=204, summary="Change your password")
def change_password(
    payload: PasswordChange,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    user_service.change_password(db, user, payload.current_password, payload.new_password)
    audit.record(db, action="user.password_change", user_id=user.id, entity_type="user", entity_id=user.id, **client_meta(request))
    db.commit()


@router.get("/auth/api-keys", response_model=list[ApiKeyOut], summary="List your API keys")
def list_api_keys(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ApiKeyOut]:
    db.refresh(user)
    return [ApiKeyOut.model_validate(k) for k in user.api_keys]


@router.post("/auth/api-keys", response_model=ApiKeyCreated, status_code=201, summary="Create an API key")
def create_api_key(
    payload: ApiKeyCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiKeyCreated:
    record, full = user_service.create_api_key(
        db, user, name=payload.name, scopes=payload.scopes, expires_in_days=payload.expires_in_days
    )
    audit.record(db, action="apikey.create", user_id=user.id, entity_type="api_key", entity_id=record.id, **client_meta(request))
    db.commit()
    return ApiKeyCreated(**ApiKeyOut.model_validate(record).model_dump(), key=full)


@router.delete("/auth/api-keys/{key_id}", status_code=204, summary="Revoke an API key")
def revoke_api_key(
    key_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    from ...core.exceptions import NotFoundError
    from ...models import ApiKey

    record = db.get(ApiKey, key_id)
    if not record or (record.user_id != user.id and user.role != Role.ADMIN.value):
        raise NotFoundError("API key not found")
    record.is_active = False
    audit.record(db, action="apikey.revoke", user_id=user.id, entity_type="api_key", entity_id=key_id, **client_meta(request))
    db.commit()
