"""Engine/session factory. Sync SQLAlchemy keeps the code simple and portable;
FastAPI runs sync dependencies in its threadpool so throughput stays fine."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ..core.config import settings
from .base import Base


def _make_engine() -> Engine:
    if settings.is_sqlite:
        connect_args = {"check_same_thread": False}
        kwargs = {"connect_args": connect_args}
        if ":memory:" in settings.database_url:
            kwargs["poolclass"] = StaticPool
        return create_engine(settings.database_url, echo=settings.db_echo, future=True, **kwargs)
    return create_engine(
        settings.database_url,
        echo=settings.db_echo,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    """Create tables directly (dev/test/first-boot). Production uses Alembic."""
    from .. import models  # noqa: F401  (ensure model modules are imported)

    Base.metadata.create_all(bind=engine)
