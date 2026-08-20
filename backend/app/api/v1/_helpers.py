"""Helpers shared by the sequence/feature routers."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...core.config import settings
from ...models import Sequence, User
from ...services import sequences as sequence_service


def version_after_feature_change(
    db: Session,
    seq: Sequence,
    *,
    message: str,
    user: User | None,
) -> None:
    """Snapshot a new version after a feature-only change, if enabled.

    Sequence edits always create a version (see ``sequences.apply_edits``); this
    keeps annotation curation undoable too, which is what users expect from a
    plasmid editor. Controlled by ``VERSION_FEATURE_EDITS``.
    """
    if not settings.version_feature_edits:
        return
    db.refresh(seq)
    seq.current_version += 1
    sequence_service.snapshot_version(
        db,
        seq,
        message=message,
        user_id=user.id if user else None,
        diff_summary={"features_only": True, "feature_count": len(seq.features)},
    )
