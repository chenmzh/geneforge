"""Analysis tools: enzymes, digestion, translation, ORFs, primers, PCR, alignment.

Small requests run inline; anything expensive (long alignments, whole-catalogue
scans of large genomes, or an explicit ``async_job``) is pushed to the job queue
and polled through ``/jobs/{id}``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from ...bio.alphabet import composition, gc_content, gc_skew_track, molecular_weight, reverse_complement
from ...bio.annotate import library_entries, transfer_annotations
from ...bio.digest import LADDERS, compatible_overhangs, enzyme_pair_suggestions, gel_simulation, ligation_matrix
from ...bio.enzymes import COMMON_ENZYMES, ENZYMES, resolve_enzymes
from ...bio.primers import add_cloning_tails, analyze_primer, gibson_primers, melting_temp
from ...bio.translate import TABLE_NAMES, codon_usage, isoelectric_point, protein_mw, six_frame_translation, translate
from ...core.config import settings
from ...core.exceptions import ValidationError
from ...db.session import get_db
from ...models import Project, ProjectRole, Sequence, User
from ...schemas.tools import (
    AlignRequest,
    AnnotateRequest,
    DigestRequest,
    EnzymeSearchRequest,
    GibsonRequest,
    MultiAlignRequest,
    OrfRequest,
    PcrRequest,
    PrimerAnalyzeRequest,
    PrimerDesignRequest,
    TransferAnnotationRequest,
    TranslateRequest,
)
from ...services import projects as project_service
from ...services import sequences as sequence_service
from ...tasks import queue as task_queue
from ..deps import get_current_user
from ._helpers import version_after_feature_change

router = APIRouter(prefix="/tools", tags=["tools"])


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _authorised_sequence(db: Session, user: User, sequence_id: str, minimum: str = ProjectRole.VIEWER.value) -> Sequence:
    seq = sequence_service.get_sequence(db, sequence_id)
    project = project_service.get_project(db, seq.project_id)
    project_service.require_access(db, project, user, minimum)
    return seq


def _resolve_input(db: Session, user: User, payload) -> tuple[str, bool, Sequence | None]:
    """Return (sequence, circular, stored_row|None) from an inline or stored input."""
    sequence_id = getattr(payload, "sequence_id", None)
    if sequence_id:
        row = _authorised_sequence(db, user, sequence_id)
        circular = row.is_circular if getattr(payload, "circular", None) is None else bool(payload.circular)
        return row.sequence, circular, row
    inline = getattr(payload, "sequence", None)
    if not inline:
        raise ValidationError("Provide either 'sequence' or 'sequence_id'")
    return inline.upper(), bool(getattr(payload, "circular", False)), None


def _maybe_async(
    db: Session,
    user: User,
    job_type: str,
    params: dict,
    *,
    force: bool = False,
    weight: int = 0,
    project: Project | None = None,
) -> tuple[bool, dict]:
    """Run inline unless the work is heavy or the caller asked for a job."""
    if force or weight > settings.async_job_length_threshold:
        job = task_queue.submit(db, job_type=job_type, params=params, user=user, project=project)
        return True, {"job_id": job.id, "status": job.status, "type": job.type}
    return False, task_queue.run_sync(db, job_type, params)


# --------------------------------------------------------------------------- #
# reference data
# --------------------------------------------------------------------------- #
@router.get("/enzymes", summary="Restriction enzyme catalogue")
def enzyme_catalogue(
    common_only: bool = False,
    search: str | None = None,
    overhang: str | None = Query(default=None, pattern="^(5'|3'|blunt)$"),
    type_iis: bool | None = None,
    _: User = Depends(get_current_user),
) -> dict:
    rows = [e.to_dict() for e in resolve_enzymes(common_only=common_only)]
    if search:
        needle = search.lower()
        rows = [r for r in rows if needle in r["name"].lower() or needle in r["site"].lower()]
    if overhang:
        rows = [r for r in rows if r["overhang"] == overhang]
    if type_iis is not None:
        rows = [r for r in rows if r["type_iis"] is type_iis]
    return {"count": len(rows), "common_set": list(COMMON_ENZYMES), "enzymes": rows, "total_catalogue": len(ENZYMES)}


@router.get("/codon-tables", summary="Supported codon tables")
def codon_tables(_: User = Depends(get_current_user)) -> dict:
    return {"tables": [{"id": tid, "name": name} for tid, name in TABLE_NAMES.items()]}


@router.get("/feature-library", summary="Auto-annotation feature library")
def feature_library(_: User = Depends(get_current_user)) -> dict:
    entries = library_entries()
    return {
        "count": len(entries),
        "entries": [
            {k: v for k, v in entry.items() if k != "signature"} | {"signature_length": len(entry.get("signature", ""))}
            for entry in entries
        ],
    }


@router.get("/ladders", summary="Available gel ladders")
def ladders(_: User = Depends(get_current_user)) -> dict:
    return {"ladders": [{"name": name, "sizes": sizes} for name, sizes in LADDERS.items()]}


# --------------------------------------------------------------------------- #
# sequence utilities
# --------------------------------------------------------------------------- #
@router.post("/reverse-complement", summary="Reverse complement a sequence")
def reverse_complement_endpoint(payload: dict, _: User = Depends(get_current_user)) -> dict:
    seq = (payload.get("sequence") or "").upper()
    if not seq:
        raise ValidationError("'sequence' is required")
    return {"sequence": reverse_complement(seq), "length": len(seq)}


@router.post("/composition", summary="Base composition, GC track and physical properties")
def composition_endpoint(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    sequence_id = payload.get("sequence_id")
    if sequence_id:
        row = _authorised_sequence(db, user, sequence_id)
        seq, circular = row.sequence, row.is_circular
    else:
        seq = (payload.get("sequence") or "").upper()
        circular = bool(payload.get("circular"))
    if not seq:
        raise ValidationError("Provide 'sequence' or 'sequence_id'")
    window = int(payload.get("window") or max(50, min(2000, max(1, len(seq) // 100))))
    return {
        "length": len(seq),
        "gc": gc_content(seq),
        "topology": "circular" if circular else "linear",
        "composition": composition(seq),
        "molecular_weight": molecular_weight(seq),
        "melting_temp": melting_temp(seq) if len(seq) > 1 else 0.0,
        "gc_track": gc_skew_track(seq, window=window),
    }


@router.post("/translate", summary="Translate a sequence (single frame or six frames)")
def translate_endpoint(
    payload: TranslateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    seq, _, _ = _resolve_input(db, user, payload)
    if payload.six_frame:
        frames = six_frame_translation(seq, payload.table_id)
        return {"table_id": payload.table_id, "frames": frames}
    frame = payload.frame
    work = reverse_complement(seq) if frame < 0 else seq
    offset = abs(frame) - 1 if frame != 0 else 0
    protein = translate(work[offset:], payload.table_id, to_stop=payload.to_stop)
    return {
        "table_id": payload.table_id,
        "frame": frame,
        "protein": protein,
        "length": len(protein),
        "molecular_weight": protein_mw(protein),
        "isoelectric_point": isoelectric_point(protein) if protein else 0.0,
        "codon_usage": codon_usage(work[offset:]) if len(work) < 100_000 else {},
    }


@router.post("/orf", summary="Find open reading frames")
def orf_endpoint(
    payload: OrfRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    seq, circular, _ = _resolve_input(db, user, payload)
    params = payload.model_dump() | {"sequence": seq, "circular": circular, "sequence_id": None}
    _, result = _maybe_async(db, user, "orf", params, weight=len(seq))
    return result


# --------------------------------------------------------------------------- #
# enzymes / digestion
# --------------------------------------------------------------------------- #
@router.post("/enzymes/search", summary="Find restriction sites")
def enzyme_search(
    payload: EnzymeSearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    seq, circular, _ = _resolve_input(db, user, payload)
    params = {
        "sequence": seq,
        "circular": circular,
        "enzymes": payload.enzymes,
        "common_only": payload.common_only,
        "unique_only": payload.unique_only,
    }
    weight = len(seq) * (1 if payload.enzymes else 3)
    _, result = _maybe_async(db, user, "enzyme_scan", params, weight=weight)
    return result


@router.post("/digest", summary="Simulate a restriction digest with a virtual gel")
def digest_endpoint(
    payload: DigestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    seq, circular, _ = _resolve_input(db, user, payload)
    params = {
        "sequence": seq,
        "circular": circular,
        "enzymes": payload.enzymes,
        "ladder": payload.ladder,
        "gel_percent": payload.gel_percent,
    }
    _, result = _maybe_async(db, user, "digest", params, weight=len(seq))
    result["ligation"] = ligation_matrix(result.get("fragments", []))[:50]
    return result


@router.post("/digest/gel", summary="Render a virtual gel from arbitrary fragment sizes")
def gel_endpoint(payload: dict, _: User = Depends(get_current_user)) -> dict:
    sizes = [int(s) for s in (payload.get("sizes") or []) if int(s) > 0]
    if not sizes:
        raise ValidationError("'sizes' must contain at least one positive integer")
    return gel_simulation(sizes, ladder=payload.get("ladder", "1kb_plus"), gel_percent=float(payload.get("gel_percent", 1.0)))


@router.post("/cloning/suggest-enzymes", summary="Suggest enzyme pairs for a cloning strategy")
def suggest_enzymes(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    sequence_id = payload.get("sequence_id")
    if sequence_id:
        row = _authorised_sequence(db, user, sequence_id)
        seq, circular = row.sequence, row.is_circular
    else:
        seq, circular = (payload.get("sequence") or "").upper(), bool(payload.get("circular"))
    if not seq:
        raise ValidationError("Provide 'sequence' or 'sequence_id'")
    region = None
    if payload.get("insert_start") is not None and payload.get("insert_end") is not None:
        region = (int(payload["insert_start"]), int(payload["insert_end"]))
    return {
        "pairs": enzyme_pair_suggestions(seq, circular=circular, insert_region=region),
    }


@router.post("/cloning/check-overhangs", summary="Check whether two sticky ends can ligate")
def check_overhangs(payload: dict, _: User = Depends(get_current_user)) -> dict:
    a = (payload.get("a") or "").upper()
    b = (payload.get("b") or "").upper()
    return {"a": a, "b": b, "compatible": compatible_overhangs(a, b)}


# --------------------------------------------------------------------------- #
# primers
# --------------------------------------------------------------------------- #
@router.post("/primers/analyze", summary="Thermodynamics and QC for one primer")
def primer_analyze(payload: PrimerAnalyzeRequest, _: User = Depends(get_current_user)) -> dict:
    stats = analyze_primer(
        payload.sequence,
        primer_conc_nM=payload.primer_conc_nM,
        na_mM=payload.na_mM,
        mg_mM=payload.mg_mM,
    )
    return stats.to_dict()


@router.post("/primers/design", summary="Design primer pairs for a target region")
def primer_design(
    payload: PrimerDesignRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    seq, _, _ = _resolve_input(db, user, payload)
    if payload.target_end <= payload.target_start:
        raise ValidationError("target_end must be greater than target_start")
    params = payload.model_dump() | {"sequence": seq, "sequence_id": None}
    _, result = _maybe_async(db, user, "primer_design", params, weight=len(seq) // 4)
    if payload.fwd_enzyme_site or payload.rev_enzyme_site:
        result["pairs"] = [
            add_cloning_tails(
                pair,
                fwd_enzyme_site=payload.fwd_enzyme_site or "",
                rev_enzyme_site=payload.rev_enzyme_site or "",
                fwd_tail="", rev_tail="", spacer="",
            )
            for pair in result.get("pairs", [])
        ]
    return result


@router.post("/primers/sequencing", summary="Tile sequencing primers along a template")
def primer_sequencing(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    sequence_id = payload.get("sequence_id")
    seq = (payload.get("sequence") or "").upper()
    if sequence_id:
        seq = _authorised_sequence(db, user, sequence_id).sequence
    if not seq:
        raise ValidationError("Provide 'sequence' or 'sequence_id'")
    params = {"sequence": seq, "read_length": int(payload.get("read_length", 800))}
    _, result = _maybe_async(db, user, "sequencing_primers", params, weight=len(seq) // 2)
    return result


@router.post("/primers/gibson", summary="Design Gibson/HiFi assembly primers")
def primer_gibson(payload: GibsonRequest, _: User = Depends(get_current_user)) -> dict:
    return gibson_primers(
        payload.insert, payload.vector_left, payload.vector_right, overlap=payload.overlap
    )


@router.post("/pcr", summary="Simulate PCR on a template")
def pcr_endpoint(
    payload: PcrRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    seq, circular, _ = _resolve_input(db, user, payload)
    params = {
        "sequence": seq,
        "circular": circular,
        "forward": payload.forward.upper(),
        "reverse": payload.reverse.upper(),
        "max_mismatches": payload.max_mismatches,
        "min_3prime_match": payload.min_3prime_match,
    }
    _, result = _maybe_async(db, user, "pcr", params, weight=len(seq))
    return result


# --------------------------------------------------------------------------- #
# alignment
# --------------------------------------------------------------------------- #
@router.post("/align", summary="Pairwise alignment (affine DP, or anchored for long inputs)")
def align_endpoint(
    payload: AlignRequest,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    query = payload.query
    target = payload.target
    if payload.query_sequence_id:
        query = _authorised_sequence(db, user, payload.query_sequence_id).sequence
    if payload.target_sequence_id:
        target = _authorised_sequence(db, user, payload.target_sequence_id).sequence
    if not query or not target:
        raise ValidationError("Provide query/target inline or by sequence id")
    params = payload.model_dump() | {
        "query": query,
        "target": target,
        "query_sequence_id": None,
        "target_sequence_id": None,
    }
    weight = (len(query) * len(target)) // 1000
    queued, result = _maybe_async(db, user, "align", params, force=payload.async_job, weight=weight)
    if queued:
        response.status_code = status.HTTP_202_ACCEPTED
    return result


@router.post("/align/multiple", summary="Multiple sequence alignment (center-star)")
def multi_align_endpoint(
    payload: MultiAlignRequest,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    entries = list(payload.sequences)
    for sid in payload.sequence_ids:
        row = _authorised_sequence(db, user, sid)
        entries.append({"name": row.name, "sequence": row.sequence})
    if len(entries) < 2:
        raise ValidationError("At least two sequences are required")
    total = sum(len(e.get("sequence") or "") for e in entries)
    params = {"sequences": entries}
    queued, result = _maybe_async(db, user, "multi_align", params, force=payload.async_job, weight=total * 2)
    if queued:
        response.status_code = status.HTTP_202_ACCEPTED
    return result


# --------------------------------------------------------------------------- #
# annotation
# --------------------------------------------------------------------------- #
@router.post("/annotate", summary="Detect known elements and ORFs")
def annotate_endpoint(
    payload: AnnotateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    seq, circular, row = _resolve_input(db, user, payload)
    params = {
        "sequence": seq,
        "circular": circular,
        "include_orfs": payload.include_orfs,
        "min_orf_aa": payload.min_orf_aa,
        "extra_library": payload.extra_library,
    }
    _, result = _maybe_async(db, user, "annotate", params, weight=len(seq))
    if payload.apply:
        if row is None:
            raise ValidationError("'apply' requires 'sequence_id'")
        project = project_service.get_project(db, row.project_id)
        project_service.require_access(db, project, user, ProjectRole.EDITOR.value)
        from ...bio.seqio import Feature as BioFeature

        features = [
            BioFeature(
                type=f["type"],
                segments=[tuple(s) for s in f["segments"]],
                strand=f["strand"],
                name=f["name"],
                qualifiers=f.get("qualifiers", {}),
                color=f.get("color"),
            )
            for f in result["features"]
        ]
        sequence_service.add_features(db, row, features)
        version_after_feature_change(db, row, message=f"Applied {len(features)} detected features", user=user)
        db.commit()
        result["applied"] = len(features)
    return result


@router.post("/annotate/transfer", summary="Transfer annotations from a reference by alignment")
def transfer_endpoint(
    payload: TransferAnnotationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    reference = _authorised_sequence(db, user, payload.reference_sequence_id)
    target = _authorised_sequence(db, user, payload.target_sequence_id)
    ref_record = sequence_service.to_bio_record(reference)
    features = transfer_annotations(ref_record, target.sequence, min_identity=payload.min_identity)
    if payload.apply and features:
        project = project_service.get_project(db, target.project_id)
        project_service.require_access(db, project, user, ProjectRole.EDITOR.value)
        sequence_service.add_features(db, target, features)
        version_after_feature_change(
            db, target, message=f"Transferred {len(features)} features from {reference.name}", user=user
        )
        db.commit()
    return {
        "reference": reference.name,
        "target": target.name,
        "transferred": [f.to_dict() for f in features],
        "count": len(features),
        "applied": bool(payload.apply and features),
    }
