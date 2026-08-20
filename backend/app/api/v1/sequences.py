"""Sequence CRUD, editing, versioning, features, import/export and primers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...bio import annotate as bio_annotate
from ...bio import seqio
from ...bio.primers import analyze_primer
from ...core.config import settings
from ...core.exceptions import NotFoundError, PayloadTooLargeError, ValidationError
from ...core.security import checksum
from ...db.session import get_db
from ...models import Feature, ImportedFile, Primer, Project, ProjectRole, Sequence, User
from ...schemas.project import Page
from ...schemas.sequence import (
    EditRequest,
    FeatureCreate,
    FeatureOut,
    FeatureUpdate,
    ImportedRecord,
    ImportRequest,
    ImportResult,
    PrimerCreate,
    PrimerOut,
    SequenceCreate,
    SequenceOut,
    SequenceStats,
    SequenceSummary,
    SequenceUpdate,
    SequenceVersionDetail,
    SequenceVersionOut,
)
from ...services import audit
from ...services import external as external_service
from ...services import projects as project_service
from ...services import sequences as sequence_service
from ..deps import client_meta, get_current_user, project_editor, project_viewer
from ._helpers import version_after_feature_change

router = APIRouter(tags=["sequences"])


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _sequence_access(
    sequence_id: str,
    db: Session,
    user: User,
    minimum: str = ProjectRole.VIEWER.value,
) -> tuple[Sequence, Project, str]:
    seq = sequence_service.get_sequence(db, sequence_id)
    project = project_service.get_project(db, seq.project_id)
    role = project_service.require_access(db, project, user, minimum)
    return seq, project, role


def seq_viewer(
    sequence_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> tuple[Sequence, Project, User]:
    seq, project, _ = _sequence_access(sequence_id, db, user, ProjectRole.VIEWER.value)
    return seq, project, user


def seq_editor(
    sequence_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> tuple[Sequence, Project, User]:
    seq, project, _ = _sequence_access(sequence_id, db, user, ProjectRole.EDITOR.value)
    return seq, project, user


def _summary(seq: Sequence, feature_count: int | None = None) -> SequenceSummary:
    data = SequenceSummary.model_validate(seq)
    data.feature_count = feature_count if feature_count is not None else len(seq.features)
    return data


def _full(seq: Sequence) -> SequenceOut:
    data = SequenceOut.model_validate(seq)
    data.features = [FeatureOut.model_validate(f) for f in seq.features]
    data.annotations = seq.annotations_json or {}
    data.feature_count = len(seq.features)
    return data


# --------------------------------------------------------------------------- #
# listing / creation
# --------------------------------------------------------------------------- #
@router.get("/projects/{project_id}/sequences", response_model=Page[SequenceSummary], summary="List sequences in a project")
def list_sequences(
    search: str | None = None,
    include_archived: bool = False,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    access: tuple[Project, User, str] = Depends(project_viewer),
    db: Session = Depends(get_db),
) -> Page[SequenceSummary]:
    project, _, _ = access
    rows, total, counts = sequence_service.list_sequences(
        db, project.id, search=search, include_archived=include_archived, page=page, size=size
    )
    return Page[SequenceSummary](
        items=[_summary(r, counts.get(r.id, 0)) for r in rows],
        total=total,
        page=page,
        size=size,
        pages=max(1, (total + size - 1) // size),
    )


@router.post("/projects/{project_id}/sequences", response_model=SequenceOut, status_code=201, summary="Create a sequence")
def create_sequence(
    payload: SequenceCreate,
    request: Request,
    access: tuple[Project, User, str] = Depends(project_editor),
    db: Session = Depends(get_db),
) -> SequenceOut:
    project, user, _ = access
    seq = sequence_service.create_sequence(
        db,
        project,
        user,
        name=payload.name,
        sequence=payload.sequence,
        description=payload.description,
        topology=payload.topology,
        molecule_type=payload.molecule_type,
        seq_type=payload.seq_type,
        features=[f.model_dump() for f in payload.features],
        annotations=payload.annotations,
        auto_annotate=payload.auto_annotate,
    )
    audit.record(
        db, action="sequence.create", user_id=user.id, entity_type="sequence", entity_id=seq.id,
        detail={"name": seq.name, "length": seq.length}, **client_meta(request),
    )
    db.commit()
    db.refresh(seq)
    return _full(seq)


@router.get("/sequences/{sequence_id}", response_model=SequenceOut, summary="Get a sequence with features")
def get_sequence(ctx: tuple[Sequence, Project, User] = Depends(seq_viewer)) -> SequenceOut:
    seq, _, _ = ctx
    return _full(seq)


@router.patch("/sequences/{sequence_id}", response_model=SequenceOut, summary="Update sequence metadata")
def update_sequence(
    payload: SequenceUpdate,
    request: Request,
    ctx: tuple[Sequence, Project, User] = Depends(seq_editor),
    db: Session = Depends(get_db),
) -> SequenceOut:
    seq, _, user = ctx
    sequence_service.update_sequence(db, seq, **payload.model_dump(exclude_none=True))
    audit.record(
        db, action="sequence.update", user_id=user.id, entity_type="sequence", entity_id=seq.id,
        detail=payload.model_dump(exclude_none=True), **client_meta(request),
    )
    db.commit()
    db.refresh(seq)
    return _full(seq)


@router.delete("/sequences/{sequence_id}", status_code=204, summary="Delete a sequence")
def delete_sequence(
    request: Request,
    ctx: tuple[Sequence, Project, User] = Depends(seq_editor),
    db: Session = Depends(get_db),
) -> None:
    seq, _, user = ctx
    audit.record(
        db, action="sequence.delete", user_id=user.id, entity_type="sequence", entity_id=seq.id,
        detail={"name": seq.name}, **client_meta(request),
    )
    sequence_service.delete_sequence(db, seq)
    db.commit()


@router.post("/sequences/{sequence_id}/copy", response_model=SequenceOut, status_code=201, summary="Duplicate a sequence")
def copy_sequence(
    target_project_id: str | None = None,
    new_name: str | None = None,
    ctx: tuple[Sequence, Project, User] = Depends(seq_viewer),
    db: Session = Depends(get_db),
) -> SequenceOut:
    seq, project, user = ctx
    target = project
    if target_project_id and target_project_id != project.id:
        target = project_service.get_project(db, target_project_id)
        project_service.require_access(db, target, user, ProjectRole.EDITOR.value)
    else:
        project_service.require_access(db, project, user, ProjectRole.EDITOR.value)
    rec = sequence_service.to_bio_record(seq)
    rec.name = new_name or f"{seq.name} copy"
    clone = sequence_service.create_from_record(db, target, user, rec)
    db.commit()
    db.refresh(clone)
    return _full(clone)


# --------------------------------------------------------------------------- #
# editing / versioning
# --------------------------------------------------------------------------- #
@router.post("/sequences/{sequence_id}/edit", response_model=SequenceOut, summary="Apply edit operations (creates a new version)")
def edit_sequence(
    payload: EditRequest,
    request: Request,
    ctx: tuple[Sequence, Project, User] = Depends(seq_editor),
    db: Session = Depends(get_db),
) -> SequenceOut:
    seq, _, user = ctx
    seq, log = sequence_service.apply_edits(
        db, seq, [op.model_dump() for op in payload.operations], user=user, message=payload.message
    )
    audit.record(
        db, action="sequence.edit", user_id=user.id, entity_type="sequence", entity_id=seq.id,
        detail={"operations": [op.op for op in payload.operations], "notes": log, "version": seq.current_version},
        **client_meta(request),
    )
    db.commit()
    db.refresh(seq)
    return _full(seq)


@router.get("/sequences/{sequence_id}/versions", response_model=list[SequenceVersionOut], summary="Version history")
def list_versions(
    ctx: tuple[Sequence, Project, User] = Depends(seq_viewer),
    db: Session = Depends(get_db),
) -> list[SequenceVersionOut]:
    seq, _, _ = ctx
    out: list[SequenceVersionOut] = []
    for row in sequence_service.list_versions(db, seq):
        item = SequenceVersionOut.model_validate(row)
        item.length = len(row.sequence_text)
        out.append(item)
    return out


@router.get("/sequences/{sequence_id}/versions/{version}", response_model=SequenceVersionDetail, summary="Read one version")
def get_version(
    version: int,
    ctx: tuple[Sequence, Project, User] = Depends(seq_viewer),
    db: Session = Depends(get_db),
) -> SequenceVersionDetail:
    seq, _, _ = ctx
    row = sequence_service.get_version(db, seq, version)
    detail = SequenceVersionDetail.model_validate(row)
    detail.sequence = row.sequence_text
    detail.features = row.features_json or []
    detail.length = len(row.sequence_text)
    return detail


@router.post("/sequences/{sequence_id}/versions/{version}/restore", response_model=SequenceOut, summary="Restore a version")
def restore_version(
    version: int,
    request: Request,
    ctx: tuple[Sequence, Project, User] = Depends(seq_editor),
    db: Session = Depends(get_db),
) -> SequenceOut:
    seq, _, user = ctx
    seq = sequence_service.restore_version(db, seq, version, user=user)
    audit.record(
        db, action="sequence.restore", user_id=user.id, entity_type="sequence", entity_id=seq.id,
        detail={"restored_from": version}, **client_meta(request),
    )
    db.commit()
    db.refresh(seq)
    return _full(seq)


# --------------------------------------------------------------------------- #
# features
# --------------------------------------------------------------------------- #
@router.get("/sequences/{sequence_id}/features", response_model=list[FeatureOut], summary="List features")
def list_features(ctx: tuple[Sequence, Project, User] = Depends(seq_viewer)) -> list[FeatureOut]:
    seq, _, _ = ctx
    return [FeatureOut.model_validate(f) for f in seq.features]


@router.post("/sequences/{sequence_id}/features", response_model=FeatureOut, status_code=201, summary="Add a feature")
def add_feature(
    payload: FeatureCreate,
    request: Request,
    ctx: tuple[Sequence, Project, User] = Depends(seq_editor),
    db: Session = Depends(get_db),
) -> FeatureOut:
    seq, _, user = ctx
    if payload.end > seq.length:
        raise ValidationError(f"Feature end {payload.end} exceeds sequence length {seq.length}")
    row = Feature(
        sequence_id=seq.id,
        **sequence_service.normalise_feature_kwargs(payload.model_dump(), seq.length),
    )
    db.add(row)
    db.flush()
    version_after_feature_change(db, seq, message=f"Added feature {row.name}", user=user)
    audit.record(
        db, action="feature.create", user_id=user.id, entity_type="sequence", entity_id=seq.id,
        detail={"name": row.name, "type": row.type, "start": row.start, "end": row.end}, **client_meta(request),
    )
    db.commit()
    db.refresh(row)
    return FeatureOut.model_validate(row)


@router.patch("/sequences/{sequence_id}/features/{feature_id}", response_model=FeatureOut, summary="Update a feature")
def update_feature(
    feature_id: str,
    payload: FeatureUpdate,
    request: Request,
    ctx: tuple[Sequence, Project, User] = Depends(seq_editor),
    db: Session = Depends(get_db),
) -> FeatureOut:
    seq, _, user = ctx
    row = db.get(Feature, feature_id)
    if not row or row.sequence_id != seq.id:
        raise NotFoundError("Feature not found")
    changes = payload.model_dump(exclude_none=True)
    merged = {
        "type": changes.get("type", row.type),
        "name": changes.get("name", row.name),
        "start": changes.get("start", row.start),
        "end": changes.get("end", row.end),
        "strand": changes.get("strand", row.strand),
        "color": changes.get("color", row.color),
        "segments": changes.get("segments", row.segments),
        "qualifiers": changes.get("qualifiers", row.qualifiers),
    }
    if "start" in changes or "end" in changes:
        merged["segments"] = [[merged["start"], merged["end"]]]
    for key, value in sequence_service.normalise_feature_kwargs(merged, seq.length).items():
        setattr(row, key, value)
    db.flush()
    version_after_feature_change(db, seq, message=f"Updated feature {row.name}", user=user)
    audit.record(
        db, action="feature.update", user_id=user.id, entity_type="sequence", entity_id=seq.id,
        detail={"feature_id": feature_id, **changes}, **client_meta(request),
    )
    db.commit()
    db.refresh(row)
    return FeatureOut.model_validate(row)


@router.delete("/sequences/{sequence_id}/features/{feature_id}", status_code=204, summary="Delete a feature")
def delete_feature(
    feature_id: str,
    request: Request,
    ctx: tuple[Sequence, Project, User] = Depends(seq_editor),
    db: Session = Depends(get_db),
) -> None:
    seq, _, user = ctx
    row = db.get(Feature, feature_id)
    if not row or row.sequence_id != seq.id:
        raise NotFoundError("Feature not found")
    name = row.name
    db.delete(row)
    db.flush()
    version_after_feature_change(db, seq, message=f"Deleted feature {name}", user=user)
    audit.record(
        db, action="feature.delete", user_id=user.id, entity_type="sequence", entity_id=seq.id,
        detail={"name": name}, **client_meta(request),
    )
    db.commit()


@router.post("/sequences/{sequence_id}/auto-annotate", response_model=SequenceOut, summary="Detect and store known features")
def auto_annotate(
    request: Request,
    include_orfs: bool = True,
    min_orf_aa: int = 80,
    replace: bool = False,
    ctx: tuple[Sequence, Project, User] = Depends(seq_editor),
    db: Session = Depends(get_db),
) -> SequenceOut:
    seq, _, user = ctx
    detected = bio_annotate.annotate_sequence(
        seq.sequence, circular=seq.is_circular, include_orfs=include_orfs, min_orf_aa=min_orf_aa
    )
    if replace:
        sequence_service.replace_features(db, seq, detected)
    else:
        existing = {(f.type, f.start, f.end, f.strand) for f in seq.features}
        new = [f for f in detected if (f.type, f.start, f.end, f.strand) not in existing]
        sequence_service.add_features(db, seq, new)
    version_after_feature_change(
        db, seq, message=f"Auto-annotated ({len(detected)} features detected)", user=user
    )
    audit.record(
        db, action="sequence.auto_annotate", user_id=user.id, entity_type="sequence", entity_id=seq.id,
        detail={"detected": len(detected), "replace": replace}, **client_meta(request),
    )
    db.commit()
    db.refresh(seq)
    return _full(seq)


# --------------------------------------------------------------------------- #
# stats / export
# --------------------------------------------------------------------------- #
@router.get("/sequences/{sequence_id}/stats", response_model=SequenceStats, summary="Composition and ORF statistics")
def sequence_stats(ctx: tuple[Sequence, Project, User] = Depends(seq_viewer)) -> SequenceStats:
    seq, _, _ = ctx
    return SequenceStats(**sequence_service.statistics(seq))


@router.get("/sequences/{sequence_id}/export", summary="Export as GenBank/FASTA/plain text")
def export_sequence(
    format: str = Query(default="genbank", pattern="^(genbank|fasta|plain)$"),
    download: bool = True,
    ctx: tuple[Sequence, Project, User] = Depends(seq_viewer),
) -> Response:
    seq, _, _ = ctx
    content, filename, media = sequence_service.export_sequence(seq, format)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if download else {}
    return Response(content=content, media_type=media if download else "text/plain", headers=headers)


# --------------------------------------------------------------------------- #
# import
# --------------------------------------------------------------------------- #
def _do_import(
    db: Session,
    project: Project,
    user: User,
    payload: bytes,
    filename: str,
    *,
    forced_format: str | None,
    auto_annotate: bool,
    name_prefix: str | None,
    request: Request | None = None,
) -> ImportResult:
    if len(payload) > settings.max_upload_bytes:
        raise PayloadTooLargeError(f"Upload exceeds {settings.max_upload_bytes} bytes")
    detected = forced_format or seqio.detect_format(payload, filename)
    try:
        if forced_format:
            text = payload.decode("utf-8", "ignore") if forced_format != "snapgene" else payload
            records = {
                "fasta": lambda: seqio.parse_fasta(text),
                "genbank": lambda: seqio.parse_genbank(text),
                "embl": lambda: seqio.parse_embl(text),
                "fastq": lambda: seqio.parse_fastq(text),
                "snapgene": lambda: seqio.parse_snapgene(payload),
                "plain": lambda: seqio.parse_any(text, filename),
            }[forced_format]()
        else:
            records = seqio.parse_any(payload, filename)
    except KeyError as exc:
        raise ValidationError(f"Unsupported format: {forced_format}") from exc
    except seqio.SequenceParseError as exc:
        raise ValidationError(str(exc)) from exc

    imported: list[ImportedRecord] = []
    skipped: list[dict] = []
    for rec in records:
        if not rec.sequence:
            skipped.append({"name": rec.name, "reason": "empty sequence"})
            continue
        try:
            row = sequence_service.create_from_record(
                db, project, user, rec,
                auto_annotate=auto_annotate,
                name_override=f"{name_prefix}{rec.name}" if name_prefix else None,
            )
        except PayloadTooLargeError as exc:
            skipped.append({"name": rec.name, "reason": exc.message})
            continue
        imported.append(
            ImportedRecord(
                sequence_id=row.id,
                name=row.name,
                length=row.length,
                topology=row.topology,
                feature_count=len(row.features),
                source_format=row.source_format,
            )
        )

    file_row = ImportedFile(
        project_id=project.id,
        user_id=user.id,
        filename=filename[:255],
        detected_format=detected,
        size_bytes=len(payload),
        checksum=checksum(payload.decode("utf-8", "ignore")[:1_000_000]),
        record_count=len(imported),
    )
    db.add(file_row)
    audit.record(
        db, action="sequence.import", user_id=user.id, entity_type="project", entity_id=project.id,
        detail={"filename": filename, "format": detected, "imported": len(imported), "skipped": len(skipped)},
        **(client_meta(request) if request else {}),
    )
    db.commit()
    return ImportResult(imported=imported, skipped=skipped, detected_format=detected, file_id=file_row.id)


@router.post(
    "/projects/{project_id}/sequences/import",
    response_model=ImportResult,
    status_code=201,
    summary="Import sequences from an uploaded file (FASTA/GenBank/EMBL/FASTQ/SnapGene .dna)",
)
async def import_file(
    request: Request,
    file: UploadFile = File(...),
    format: str | None = Query(default=None),
    auto_annotate: bool = Query(default=False),
    name_prefix: str | None = Query(default=None),
    access: tuple[Project, User, str] = Depends(project_editor),
    db: Session = Depends(get_db),
) -> ImportResult:
    project, user, _ = access
    payload = await file.read()
    return _do_import(
        db, project, user, payload, file.filename or "upload",
        forced_format=format, auto_annotate=auto_annotate, name_prefix=name_prefix, request=request,
    )


@router.post(
    "/projects/{project_id}/sequences/import-text",
    response_model=ImportResult,
    status_code=201,
    summary="Import sequences from pasted text or an allow-listed URL",
)
def import_text(
    payload: ImportRequest,
    request: Request,
    access: tuple[Project, User, str] = Depends(project_editor),
    db: Session = Depends(get_db),
) -> ImportResult:
    project, user, _ = access
    if payload.url:
        content = external_service.fetch_url(payload.url)
        filename = payload.filename or payload.url.rsplit("/", 1)[-1] or "download"
    elif payload.content:
        content = payload.content
        filename = payload.filename or "pasted.txt"
    else:
        raise ValidationError("Provide either 'content' or 'url'")
    return _do_import(
        db, project, user, content.encode("utf-8"), filename,
        forced_format=payload.format, auto_annotate=payload.auto_annotate,
        name_prefix=payload.name_prefix, request=request,
    )


# --------------------------------------------------------------------------- #
# primers (stored per project)
# --------------------------------------------------------------------------- #
@router.get("/projects/{project_id}/primers", response_model=list[PrimerOut], summary="List stored primers")
def list_primers(
    sequence_id: str | None = None,
    access: tuple[Project, User, str] = Depends(project_viewer),
    db: Session = Depends(get_db),
) -> list[PrimerOut]:
    project, _, _ = access
    stmt = select(Primer).where(Primer.project_id == project.id)
    if sequence_id:
        stmt = stmt.where(Primer.sequence_id == sequence_id)
    return [PrimerOut.model_validate(p) for p in db.scalars(stmt.order_by(Primer.created_at.desc()))]


@router.post("/projects/{project_id}/primers", response_model=PrimerOut, status_code=201, summary="Save a primer")
def create_primer(
    payload: PrimerCreate,
    access: tuple[Project, User, str] = Depends(project_editor),
    db: Session = Depends(get_db),
) -> PrimerOut:
    project, user, _ = access
    stats = analyze_primer(payload.sequence)
    row = Primer(
        project_id=project.id,
        sequence_id=payload.sequence_id,
        name=payload.name,
        seq=stats.sequence,
        tm=stats.tm,
        gc_content=stats.gc,
        binding_start=payload.binding_start,
        binding_end=payload.binding_end,
        strand=payload.strand,
        notes=payload.notes,
        stats=stats.to_dict(),
        created_by_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return PrimerOut.model_validate(row)


@router.delete("/primers/{primer_id}", status_code=204, summary="Delete a stored primer")
def delete_primer(
    primer_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    row = db.get(Primer, primer_id)
    if not row:
        raise NotFoundError("Primer not found")
    project = project_service.get_project(db, row.project_id)
    project_service.require_access(db, project, user, ProjectRole.EDITOR.value)
    db.delete(row)
    db.commit()
