"""Long-running analysis handlers, addressable by job type.

Handlers are plain functions ``(db, params, progress) -> dict`` so the same code
runs under Celery, under the in-process fallback worker, or synchronously in a
request. Keeping them free of FastAPI/Celery imports is what makes that possible.
"""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from ..bio import annotate as bio_annotate
from ..bio.align import ScoreScheme, align_pair, multiple_alignment
from ..bio.digest import digest, enzyme_pair_suggestions, gel_simulation
from ..bio.primers import DesignParams, design_primer_pairs, sequencing_primers, simulate_pcr
from ..core.exceptions import NotFoundError, ValidationError

ProgressFn = Callable[[float, str | None], None]


def _load_sequence(db: Session, sequence_id: str) -> tuple[str, bool, str]:
    from ..models import Sequence

    row = db.get(Sequence, sequence_id)
    if not row:
        raise NotFoundError(f"Sequence {sequence_id} not found")
    return row.sequence, row.is_circular, row.name


def _resolve(db: Session, params: dict, *, key: str = "sequence", id_key: str = "sequence_id") -> tuple[str, bool]:
    if params.get(id_key):
        seq, circular, _ = _load_sequence(db, params[id_key])
        if params.get("circular") is not None:
            circular = bool(params["circular"])
        return seq, circular
    seq = params.get(key) or ""
    if not seq:
        raise ValidationError(f"Provide '{key}' or '{id_key}'")
    return seq, bool(params.get("circular"))


def handle_align(db: Session, params: dict, progress: ProgressFn) -> dict:
    query = params.get("query")
    target = params.get("target")
    if params.get("query_sequence_id"):
        query = _load_sequence(db, params["query_sequence_id"])[0]
    if params.get("target_sequence_id"):
        target = _load_sequence(db, params["target_sequence_id"])[0]
    if not query or not target:
        raise ValidationError("Both query and target sequences are required")
    progress(0.2, "aligning")
    scheme = ScoreScheme(
        match=int(params.get("match", 2)),
        mismatch=int(params.get("mismatch", -3)),
        gap_open=int(params.get("gap_open", -6)),
        gap_extend=int(params.get("gap_extend", -2)),
    )
    result = align_pair(
        query,
        target,
        mode=params.get("mode", "global"),
        scheme=scheme,
        try_reverse_complement=bool(params.get("try_reverse_complement", True)),
    )
    progress(1.0, "done")
    return result.to_dict()


def handle_multi_align(db: Session, params: dict, progress: ProgressFn) -> dict:
    entries = list(params.get("sequences") or [])
    for sid in params.get("sequence_ids") or []:
        seq, _, name = _load_sequence(db, sid)
        entries.append({"name": name, "sequence": seq})
    if len(entries) < 2:
        raise ValidationError("At least two sequences are required")
    progress(0.3, "aligning")
    result = multiple_alignment(entries)
    progress(1.0, "done")
    return result


def handle_digest(db: Session, params: dict, progress: ProgressFn) -> dict:
    seq, circular = _resolve(db, params)
    enzymes = params.get("enzymes") or []
    if not enzymes:
        raise ValidationError("At least one enzyme is required")
    progress(0.4, "digesting")
    result = digest(seq, enzymes, circular=circular)
    result["gel"] = gel_simulation(
        result["fragment_sizes"],
        ladder=params.get("ladder", "1kb_plus"),
        gel_percent=float(params.get("gel_percent", 1.0)),
    )
    progress(1.0, "done")
    return result


def handle_primer_design(db: Session, params: dict, progress: ProgressFn) -> dict:
    seq, _ = _resolve(db, params)
    design = DesignParams(
        min_len=int(params.get("min_len", 18)),
        max_len=int(params.get("max_len", 27)),
        opt_tm=float(params.get("opt_tm", 60.0)),
        min_tm=float(params.get("min_tm", 57.0)),
        max_tm=float(params.get("max_tm", 65.0)),
        max_tm_diff=float(params.get("max_tm_diff", 3.0)),
        product_min=int(params.get("product_min", 0)),
        product_max=int(params.get("product_max", 0)),
    )
    progress(0.3, "designing")
    pairs = design_primer_pairs(
        seq,
        int(params.get("target_start", 0)),
        int(params.get("target_end", len(seq))),
        params=design,
        max_pairs=int(params.get("max_pairs", 5)),
    )
    progress(1.0, "done")
    return {"pairs": pairs, "count": len(pairs)}


def handle_sequencing_primers(db: Session, params: dict, progress: ProgressFn) -> dict:
    seq, _ = _resolve(db, params)
    progress(0.3, "designing")
    primers = sequencing_primers(seq, read_length=int(params.get("read_length", 800)))
    progress(1.0, "done")
    return {"primers": primers, "count": len(primers)}


def handle_pcr(db: Session, params: dict, progress: ProgressFn) -> dict:
    seq, circular = _resolve(db, params)
    progress(0.4, "simulating")
    result = simulate_pcr(
        seq,
        params.get("forward", ""),
        params.get("reverse", ""),
        circular=circular,
        max_mismatches=int(params.get("max_mismatches", 3)),
        min_3prime_match=int(params.get("min_3prime_match", 12)),
    )
    progress(1.0, "done")
    return result


def handle_annotate(db: Session, params: dict, progress: ProgressFn) -> dict:
    seq, circular = _resolve(db, params)
    progress(0.3, "scanning")
    features = bio_annotate.annotate_sequence(
        seq,
        circular=circular,
        extra_library=params.get("extra_library") or [],
        include_orfs=bool(params.get("include_orfs", True)),
        min_orf_aa=int(params.get("min_orf_aa", 80)),
    )
    progress(1.0, "done")
    return {"features": [f.to_dict() for f in features], "count": len(features)}


def handle_orf(db: Session, params: dict, progress: ProgressFn) -> dict:
    seq, circular = _resolve(db, params)
    orfs = bio_annotate.find_orfs(
        seq,
        min_aa=int(params.get("min_aa", 50)),
        circular=circular,
        table_id=int(params.get("table_id", 1)),
        both_strands=bool(params.get("both_strands", True)),
        require_start=bool(params.get("require_start", True)),
    )
    progress(1.0, "done")
    return {"orfs": [o.to_dict() for o in orfs], "count": len(orfs)}


def handle_enzyme_scan(db: Session, params: dict, progress: ProgressFn) -> dict:
    from ..bio.enzymes import find_sites, resolve_enzymes, site_summary

    seq, circular = _resolve(db, params)
    enzymes = resolve_enzymes(params.get("enzymes"), common_only=bool(params.get("common_only", True)))
    progress(0.4, "scanning")
    sites = find_sites(seq, enzymes, circular=circular)
    summary = site_summary(sites)
    if params.get("unique_only"):
        summary = [row for row in summary if row["unique"]]
        keep = {row["enzyme"] for row in summary}
        sites = [s for s in sites if s.enzyme in keep]
    progress(1.0, "done")
    return {
        "sites": [s.to_dict() for s in sites],
        "summary": summary,
        "suggestions": enzyme_pair_suggestions(seq, circular=circular)[:15],
    }


HANDLERS: dict[str, Callable[[Session, dict, ProgressFn], dict]] = {
    "align": handle_align,
    "multi_align": handle_multi_align,
    "digest": handle_digest,
    "primer_design": handle_primer_design,
    "sequencing_primers": handle_sequencing_primers,
    "pcr": handle_pcr,
    "annotate": handle_annotate,
    "orf": handle_orf,
    "enzyme_scan": handle_enzyme_scan,
}


def get_handler(job_type: str) -> Callable[[Session, dict, ProgressFn], dict]:
    handler = HANDLERS.get(job_type)
    if handler is None:
        raise ValidationError(f"Unknown job type '{job_type}'. Known: {', '.join(sorted(HANDLERS))}")
    return handler
