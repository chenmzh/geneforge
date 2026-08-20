"""SQLAlchemy declarative base + shared column mixins."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Normalise a datetime read back from the database to aware UTC.

    SQLite (and some drivers) drop the tzinfo, so naive values coming out of the
    database must be re-tagged before they are compared with ``utcnow()``.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    """Declarative base with snake_case table names."""

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        name = cls.__name__
        out = [name[0].lower()]
        for ch in name[1:]:
            out.append(f"_{ch.lower()}" if ch.isupper() else ch)
        return "".join(out) + "s"


class UUIDMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )
