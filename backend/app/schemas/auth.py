"""Pydantic v2 schemas — auth, users, API keys."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .types import Email


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LoginRequest(BaseModel):
    username: str = Field(description="Username or email")
    password: str


class UserCreate(BaseModel):
    email: Email
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)
    full_name: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, description="Admin only; defaults to editor")


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: Email | None = None
    role: str | None = None
    is_active: bool | None = None
    settings: dict | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


class UserOut(ORMModel):
    id: str
    email: str
    username: str
    full_name: str | None = None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class ApiKeyCreate(BaseModel):
    name: str = Field(max_length=120)
    scopes: list[str] = Field(default_factory=list)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyOut(ORMModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    is_active: bool
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="Full API key — shown only once")


class AuditLogOut(ORMModel):
    id: str
    created_at: datetime
    user_id: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    ip_address: str | None = None
    detail: dict = Field(default_factory=dict)
