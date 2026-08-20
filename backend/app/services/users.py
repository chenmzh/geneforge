"""User and API-key services."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.exceptions import ConflictError, NotFoundError, ValidationError
from ..core.security import generate_api_key, hash_api_key, hash_password, password_problems, verify_password
from ..db.base import ensure_utc, utcnow
from ..models import ApiKey, Role, User


def get_by_id(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if not user:
        raise NotFoundError("User not found")
    return user


def find_by_login(db: Session, login: str) -> User | None:
    stmt = select(User).where(
        or_(func.lower(User.email) == login.lower(), func.lower(User.username) == login.lower())
    )
    return db.scalars(stmt).first()


def create_user(
    db: Session,
    *,
    email: str,
    username: str,
    password: str,
    full_name: str | None = None,
    role: str = Role.EDITOR.value,
) -> User:
    problems = password_problems(password)
    if problems:
        raise ValidationError("Weak password", detail=problems)
    if db.scalars(select(User).where(func.lower(User.email) == email.lower())).first():
        raise ConflictError("Email already registered")
    if db.scalars(select(User).where(func.lower(User.username) == username.lower())).first():
        raise ConflictError("Username already taken")
    if role not in {r.value for r in Role}:
        raise ValidationError(f"Unknown role: {role}")
    user = User(
        email=email.lower(),
        username=username,
        full_name=full_name,
        hashed_password=hash_password(password),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def authenticate(db: Session, login: str, password: str) -> User:
    from ..core.exceptions import AuthenticationError

    user = find_by_login(db, login)
    if not user or not verify_password(password, user.hashed_password):
        raise AuthenticationError("Incorrect username or password")
    if not user.is_active:
        raise AuthenticationError("User account is disabled")
    user.last_login_at = utcnow()
    db.flush()
    return user


def change_password(db: Session, user: User, current: str, new: str) -> None:
    from ..core.exceptions import AuthenticationError

    if not verify_password(current, user.hashed_password):
        raise AuthenticationError("Current password is incorrect")
    problems = password_problems(new)
    if problems:
        raise ValidationError("Weak password", detail=problems)
    user.hashed_password = hash_password(new)
    db.flush()


def create_api_key(
    db: Session,
    user: User,
    *,
    name: str,
    scopes: list[str] | None = None,
    expires_in_days: int | None = None,
) -> tuple[ApiKey, str]:
    full, prefix, hashed = generate_api_key()
    record = ApiKey(
        user_id=user.id,
        name=name,
        prefix=prefix,
        hashed_key=hashed,
        scopes=scopes or [],
        expires_at=utcnow() + timedelta(days=expires_in_days) if expires_in_days else None,
    )
    db.add(record)
    db.flush()
    return record, full


def resolve_api_key(db: Session, raw_key: str) -> User | None:
    hashed = hash_api_key(raw_key)
    record = db.scalars(select(ApiKey).where(ApiKey.hashed_key == hashed)).first()
    if not record or not record.is_active:
        return None
    expires_at = ensure_utc(record.expires_at)
    if expires_at and expires_at < utcnow():
        return None
    record.last_used_at = utcnow()
    user = db.get(User, record.user_id)
    if user and user.is_active:
        db.flush()
        return user
    return None
