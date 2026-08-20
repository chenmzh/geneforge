"""Audit trail helper — every mutating action goes through here."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..models import AuditLog


def record(
    db: Session,
    *,
    action: str,
    user_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    detail: dict[str, Any] | None = None,
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        created_at=utcnow(),
        action=action,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:255] or None,
        detail=detail or {},
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry
