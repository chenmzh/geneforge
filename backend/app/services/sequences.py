"""Sequence service: persistence, immutable versioning, features, import/export."""
from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Sequence as Seq

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..bio import annotate as bio_annotate
from ..bio import edit as bio_edit
from ..bio import seqio
from ..bio.alphabet import clean_sequence, gc_content, molecular_weight
from ..bio.primers import melting_temp
from ..core.config import settings
from ..core.exceptions import NotFoundError, PayloadTooLargeError, ValidationError
from ..core.security import checksum
from ..models import Feature, Project, Sequence, SequenceVersion, Topology, User


# --------------------------------------------------------------------------- #
# Conversion helpers between ORM rows and the bio engine dataclasses
# --------------------------------------------------------------------------- #
def feature_to_bio(row: Feature) -> seqio.Feature:
    segments = [tuple(s) for s in (row.segments or [])] or [(row.start, row.end)]
    return seqio.Feature(
        type=row.type,
        segments=[(int(a), int(b)) for a, b in segments],
        strand=row.strand,
        name=row.name,
        qualifiers=dict(row.qualifiers or {}),
        color=row.color,
    )


def bio_to_feature_kwargs(feat: seqio.Feature) -> dict:
    return {
        "type": feat.type,
        "name": feat.name[:255],
        "start": feat.start,
        "end": feat.end,
        "strand": feat.strand,
        "color": feat.color,
        "segments": [list(s) for s in feat.segments],
        "qualifiers": feat.qualifiers or {},
    }


def to_bio_record(seq: Sequence) -> seqio.SeqRecord:
    return seqio.SeqRecord(
        name=seq.name,
        sequence=seq.sequence,
        description=seq.description or "",
        topology=seq.topology,
        molecule_type=seq.molecule_type or "ds-DNA",
        features=[feature_to_bio(f) for f in seq.features],
        annotations=dict(seq.annotations_json or {}),
        source_format=seq.source_format,
    )


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def get_sequence(db: Session, sequence_id: str, *, with_features: bool = True) -> Sequence:
    stmt = select(Sequence).where(Sequence.id == sequence_id)
    if with_features:
        stmt = stmt.options(selectinload(Sequence.features))
    seq = db.scalars(stmt).first()
    if not seq:
        raise NotFoundError("Sequence not found")
    return seq


def list_sequences(
    db: Session,
    project_id: str,
    *,
    search: str | None = None,
    include_archived: bool = False,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Sequence], int, dict]:
    stmt = select(Sequence).where(Sequence.project_id == project_id)
    if not include_archived:
        stmt = stmt.where(Sequence.is_archived.is_(False))
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(func.lower(Sequence.name).like(like) | func.lower(Sequence.description).like(like))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(Sequence.updated_at.desc()).offset((page - 1) * size).limit(size)))
    counts_stmt = (
        select(Feature.sequence_id, func.count(Feature.id))
        .where(Feature.sequence_id.in_([r.id for r in rows] or [""]))
        .group_by(Feature.sequence_id)
    )
    counts = dict(db.execute(counts_stmt).all())
    return rows, total, counts


# --------------------------------------------------------------------------- #
# Mutations
# --------------------------------------------------------------------------- #
def _validate_sequence(text: str) -> str:
    cleaned = clean_sequence(text)
    if len(cleaned) > settings.max_sequence_length:
        raise PayloadTooLargeError(
            f"Sequence exceeds the configured limit of {settings.max_sequence_length} bp"
        )
    return cleaned


def _refresh_derived(seq: Sequence) -> None:
    seq.length = len(seq.sequence)
    seq.gc_content = gc_content(seq.sequence)
    seq.checksum = checksum(seq.sequence)


def snapshot_version(
    db: Session,
    seq: Sequence,
    *,
    message: str,
    user_id: str | None = None,
    diff_summary: dict | None = None,
) -> SequenceVersion:
    version = SequenceVersion(
        sequence_id=seq.id,
        version=seq.current_version,
        sequence_text=seq.sequence,
        features_json=[bio_to_feature_kwargs(feature_to_bio(f)) for f in seq.features],
        topology=seq.topology,
        message=message[:500],
        diff_summary=diff_summary or {},
        created_by_id=user_id,
    )
    db.add(version)
    db.flush()
    return version


def create_sequence(
    db: Session,
    project: Project,
    user: User | None,
    *,
    name: str,
    sequence: str = "",
    description: str | None = None,
    topology: str = Topology.LINEAR.value,
    molecule_type: str = "ds-DNA",
    seq_type: str = "dna",
    features: Iterable[dict] | None = None,
    annotations: dict | None = None,
    source_format: str = "manual",
    auto_annotate: bool = False,
) -> Sequence:
    cleaned = _validate_sequence(sequence)
    row = Sequence(
        project_id=project.id,
        name=name,
        description=description,
        sequence=cleaned,
        topology=topology,
        molecule_type=molecule_type,
        seq_type=seq_type,
        annotations_json=annotations or {},
        source_format=source_format,
        created_by_id=user.id if user else None,
        current_version=1,
    )
    _refresh_derived(row)
    db.add(row)
    db.flush()

    incoming: list[dict] = list(features or [])
    if auto_annotate and cleaned:
        detected = bio_annotate.annotate_sequence(
            cleaned, circular=topology == Topology.CIRCULAR.value
        )
        incoming.extend(bio_to_feature_kwargs(f) for f in detected)
    for kwargs in incoming:
        db.add(Feature(sequence_id=row.id, **normalise_feature_kwargs(kwargs, row.length)))
    db.flush()
    db.refresh(row)
    snapshot_version(db, row, message="Initial version", user_id=user.id if user else None)
    return row


def normalise_feature_kwargs(kwargs: dict, seq_length: int) -> dict:
    data = dict(kwargs)
    segments = [list(s) for s in (data.get("segments") or [])]
    if not segments:
        segments = [[int(data.get("start", 0)), int(data.get("end", 0))]]
    clipped = []
    for start, end in segments:
        start = max(0, min(int(start), seq_length))
        end = max(0, min(int(end), seq_length))
        if end > start:
            clipped.append([start, end])
    if not clipped:
        clipped = [[0, min(1, seq_length)]]
    data["segments"] = clipped
    data["start"] = min(s for s, _ in clipped)
    data["end"] = max(e for _, e in clipped)
    data.setdefault("type", "misc_feature")
    data.setdefault("strand", 1)
    data["name"] = (data.get("name") or data["type"])[:255]
    data.setdefault("qualifiers", {})
    data.setdefault("color", None)
    return {k: v for k, v in data.items() if k in {"type", "name", "start", "end", "strand", "color", "segments", "qualifiers"}}


def create_from_record(
    db: Session,
    project: Project,
    user: User | None,
    rec: seqio.SeqRecord,
    *,
    auto_annotate: bool = False,
    name_override: str | None = None,
) -> Sequence:
    return create_sequence(
        db,
        project,
        user,
        name=(name_override or rec.name or "imported")[:200],
        sequence=rec.sequence,
        description=rec.description,
        topology=Topology.CIRCULAR.value if rec.is_circular else Topology.LINEAR.value,
        molecule_type=rec.molecule_type,
        features=[bio_to_feature_kwargs(f) for f in rec.features],
        annotations=rec.annotations,
        source_format=rec.source_format,
        auto_annotate=auto_annotate,
    )


def update_sequence(db: Session, seq: Sequence, **changes) -> Sequence:
    for key, value in changes.items():
        if value is None:
            continue
        if key == "annotations":
            seq.annotations_json = value
        elif hasattr(seq, key):
            setattr(seq, key, value)
    _refresh_derived(seq)
    db.flush()
    return seq


def delete_sequence(db: Session, seq: Sequence) -> None:
    db.delete(seq)
    db.flush()


def replace_features(db: Session, seq: Sequence, features: Seq[seqio.Feature]) -> None:
    for existing in list(seq.features):
        db.delete(existing)
    db.flush()
    for feat in features:
        db.add(Feature(sequence_id=seq.id, **normalise_feature_kwargs(bio_to_feature_kwargs(feat), seq.length)))
    db.flush()
    db.refresh(seq)


def add_features(db: Session, seq: Sequence, features: Seq[seqio.Feature]) -> list[Feature]:
    created: list[Feature] = []
    for feat in features:
        row = Feature(sequence_id=seq.id, **normalise_feature_kwargs(bio_to_feature_kwargs(feat), seq.length))
        db.add(row)
        created.append(row)
    db.flush()
    db.refresh(seq)
    return created


def apply_edits(
    db: Session,
    seq: Sequence,
    operations: Seq[dict],
    *,
    user: User | None = None,
    message: str | None = None,
) -> tuple[Sequence, list[str]]:
    """Apply a list of edit operations atomically, creating a new version."""
    sequence = seq.sequence
    features = [feature_to_bio(f) for f in seq.features]
    topology = seq.topology
    log: list[str] = []
    before_length = len(sequence)

    for op in operations:
        kind = op.get("op")
        if kind == "insert":
            position = int(op.get("position") if op.get("position") is not None else op.get("start") or 0)
            sequence, features, note = bio_edit.insert_sequence(sequence, features, position, op.get("payload") or "")
        elif kind == "delete":
            sequence, features, note = bio_edit.delete_range(sequence, features, int(op.get("start") or 0), int(op.get("end") or 0))
        elif kind == "replace":
            sequence, features, note = bio_edit.replace_range(
                sequence, features, int(op.get("start") or 0), int(op.get("end") or 0), op.get("payload") or ""
            )
        elif kind == "reverse_complement":
            sequence, features, note = bio_edit.reverse_complement_all(sequence, features)
        elif kind == "reverse_complement_range":
            sequence, features, note = bio_edit.reverse_complement_range(
                sequence, features, int(op.get("start") or 0), int(op.get("end") or 0)
            )
        elif kind == "set_origin":
            if topology != Topology.CIRCULAR.value:
                raise ValidationError("set_origin requires a circular sequence")
            sequence, features, note = bio_edit.set_origin(sequence, features, int(op.get("origin") or 0))
        elif kind == "set_topology":
            topology = op.get("topology") or topology
            note = f"Set topology to {topology}"
        else:
            raise ValidationError(f"Unsupported operation: {kind}")
        log.append(note)

    cleaned = _validate_sequence(sequence)
    seq.sequence = cleaned
    seq.topology = topology
    seq.current_version += 1
    _refresh_derived(seq)
    replace_features(db, seq, features)
    snapshot_version(
        db,
        seq,
        message=message or "; ".join(log),
        user_id=user.id if user else None,
        diff_summary={
            "operations": [op.get("op") for op in operations],
            "length_before": before_length,
            "length_after": seq.length,
            "delta": seq.length - before_length,
            "notes": log,
        },
    )
    db.flush()
    return seq, log


def list_versions(db: Session, seq: Sequence) -> list[SequenceVersion]:
    return list(
        db.scalars(
            select(SequenceVersion)
            .where(SequenceVersion.sequence_id == seq.id)
            .order_by(SequenceVersion.version.desc())
        )
    )


def get_version(db: Session, seq: Sequence, version: int) -> SequenceVersion:
    row = db.scalars(
        select(SequenceVersion).where(
            SequenceVersion.sequence_id == seq.id, SequenceVersion.version == version
        )
    ).first()
    if not row:
        raise NotFoundError(f"Version {version} not found")
    return row


def restore_version(db: Session, seq: Sequence, version: int, *, user: User | None = None) -> Sequence:
    snapshot = get_version(db, seq, version)
    seq.sequence = snapshot.sequence_text
    seq.topology = snapshot.topology
    seq.current_version += 1
    _refresh_derived(seq)
    bio_features = [
        seqio.Feature(
            type=f.get("type", "misc_feature"),
            segments=[tuple(s) for s in f.get("segments", [])] or [(f.get("start", 0), f.get("end", 0))],
            strand=f.get("strand", 1),
            name=f.get("name", ""),
            qualifiers=f.get("qualifiers", {}),
            color=f.get("color"),
        )
        for f in (snapshot.features_json or [])
    ]
    replace_features(db, seq, bio_features)
    snapshot_version(
        db,
        seq,
        message=f"Restored version {version}",
        user_id=user.id if user else None,
        diff_summary={"restored_from": version},
    )
    db.flush()
    return seq


def export_sequence(seq: Sequence, fmt: str = "genbank") -> tuple[str, str, str]:
    """Return (content, filename, media_type)."""
    rec = to_bio_record(seq)
    content = seqio.serialize(rec, fmt)
    ext = {"genbank": "gb", "fasta": "fasta", "plain": "txt"}.get(fmt, "txt")
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in seq.name) or "sequence"
    media = "chemical/seq-na-genbank" if fmt == "genbank" else "text/plain"
    return content, f"{safe}.{ext}", media


def statistics(seq: Sequence) -> dict:
    stats = bio_annotate.sequence_statistics(seq.sequence, circular=seq.is_circular)
    from ..bio.alphabet import gc_skew_track

    stats["gc_track"] = gc_skew_track(seq.sequence, window=max(50, min(2000, max(1, seq.length // 100))))
    stats["molecular_weight"] = molecular_weight(seq.sequence)
    stats["melting_temp"] = melting_temp(seq.sequence) if seq.length >= 2 else 0.0
    stats.pop("first_frame_protein", None)
    return stats
