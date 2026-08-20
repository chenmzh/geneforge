"""Pydantic schemas — projects, membership, pagination."""
from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    tags: list[str] | None = None
    metadata: dict | None = None
    is_archived: bool | None = None


class MemberOut(ORMModel):
    id: str
    user_id: str
    role: str
    username: str | None = None
    email: str | None = None


class MemberAdd(BaseModel):
    user_id: str | None = None
    username: str | None = None
    email: str | None = None
    role: str = Field(default="viewer", pattern="^(owner|editor|viewer)$")


class ProjectOut(ORMModel):
    id: str
    name: str
    slug: str
    description: str | None = None
    owner_id: str
    is_archived: bool
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    sequence_count: int = 0
    my_role: str | None = None


class ProjectDetail(ProjectOut):
    members: list[MemberOut] = Field(default_factory=list)
    # ``metadata`` is reserved on SQLAlchemy declarative classes, so the ORM column
    # is ``metadata_json``; the alias keeps the public API field name clean.
    metadata: dict = Field(
        default_factory=dict,
        validation_alias="metadata_json",
    )
