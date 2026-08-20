"""Password hashing, JWT issuing/verification and API-key helpers.

Uses only the standard library for crypto primitives (PBKDF2-HMAC-SHA256) plus
PyJWT for tokens, so there is no native build dependency in the image.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from .config import settings

ALGORITHM = "HS256"
_HASH_PREFIX = "pbkdf2_sha256"


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str, *, iterations: int | None = None) -> str:
    iterations = iterations or settings.pbkdf2_iterations
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        [
            _HASH_PREFIX,
            str(iterations),
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode(),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        prefix, iterations, salt_b64, digest_b64 = stored.split("$")
        if prefix != _HASH_PREFIX:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(candidate, expected)
    except (ValueError, TypeError):
        return False


def password_problems(password: str) -> list[str]:
    problems: list[str] = []
    if len(password) < settings.password_min_length:
        problems.append(f"Password must be at least {settings.password_min_length} characters")
    if not any(c.isalpha() for c in password):
        problems.append("Password must contain a letter")
    if not any(c.isdigit() for c in password):
        problems.append("Password must contain a digit")
    return problems


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(tz=UTC)


def create_token(subject: str, *, token_type: str = "access", expires_delta: timedelta | None = None, **claims: Any) -> str:
    if expires_delta is None:
        expires_delta = (
            timedelta(minutes=settings.access_token_ttl_minutes)
            if token_type == "access"
            else timedelta(days=settings.refresh_token_ttl_days)
        )
    issued = _now()
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(issued.timestamp()),
        "exp": int((issued + expires_delta).timestamp()),
        "jti": secrets.token_urlsafe(12),
        **claims,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(subject: str, **claims: Any) -> str:
    return create_token(subject, token_type="access", **claims)


def create_refresh_token(subject: str, **claims: Any) -> str:
    return create_token(subject, token_type="refresh", **claims)


def decode_token(token: str, *, expected_type: str | None = None) -> dict:
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Expected {expected_type} token")
    return payload


# --------------------------------------------------------------------------- #
# API keys (for scripted pipelines / LIMS integration)
# --------------------------------------------------------------------------- #
API_KEY_PREFIX = "gf"


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, hashed_key). The full key is shown once."""
    raw = secrets.token_urlsafe(32)
    prefix = secrets.token_hex(4)
    full = f"{API_KEY_PREFIX}_{prefix}_{raw}"
    hashed = hashlib.sha256(full.encode("utf-8")).hexdigest()
    return full, prefix, hashed


def hash_api_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
