"""ORF discovery and auto-annotation.

Auto-annotation is data driven: the shipped library lives in
``feature_library.json`` and can be replaced or extended per deployment, and a
caller may pass extra entries at request time.  Annotations can also be
transferred from a reference construct by alignment, which is how labs usually
propagate curated maps onto sequencing results.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .align import align_pair
from .alphabet import gc_content, reverse_complement
from .seqio import Feature, SeqRecord
from .translate import START_CODONS, get_table, translate

LIBRARY_PATH = Path(__file__).with_name("feature_library.json")


@lru_cache(maxsize=1)
def load_library() -> list[dict]:
    try:
        data = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
        return list(data.get("features", []))
    except (OSError, json.JSONDecodeError):
        return []


@dataclass
class ORF:
    start: int
    end: int
    strand: int
    frame: int
    length: int
    protein: str
    start_codon: str
    stop_codon: str
    crosses_origin: bool = False

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "strand": self.strand,
            "frame": self.frame,
            "length": self.length,
            "aa_length": len(self.protein),
            "protein": self.protein,
            "start_codon": self.start_codon,
            "stop_codon": self.stop_codon,
            "crosses_origin": self.crosses_origin,
        }


def find_orfs(
    sequence: str,
    *,
    min_aa: int = 50,
    circular: bool = False,
    table_id: int = 1,
    require_start: bool = True,
    both_strands: bool = True,
) -> list[ORF]:
    """Find open reading frames on one or both strands."""
    seq = sequence.upper()
    n = len(seq)
    if n < 6:
        return []
    table = get_table(table_id)
    starts = set(START_CODONS.get(table_id, ("ATG",)))
    orfs: list[ORF] = []

    strands = (1, -1) if both_strands else (1,)
    for strand in strands:
        work = seq if strand == 1 else reverse_complement(seq)
        scan = work + work[: min(n, 3000)] if circular else work
        for frame in range(3):
            i = frame
            while i + 3 <= len(scan):
                codon = scan[i : i + 3]
                if (codon in starts) if require_start else True:
                    j = i
                    protein_chars: list[str] = []
                    stop_codon = ""
                    while j + 3 <= len(scan):
                        cod = scan[j : j + 3]
                        aa = table.get(cod, "X")
                        if aa == "*":
                            stop_codon = cod
                            break
                        protein_chars.append(aa)
                        j += 3
                        if circular and j - i > n:
                            break
                    if len(protein_chars) >= min_aa and (stop_codon or not require_start):
                        end = j + 3 if stop_codon else j
                        crosses = end > n
                        if strand == 1:
                            s0, e0 = i, end
                        else:
                            s0, e0 = n - (end % n if crosses else end), n - i
                            if crosses:
                                s0 = (n - end) % n
                        orfs.append(
                            ORF(
                                start=s0 % n if crosses else s0,
                                end=e0 if not crosses else (e0 % n),
                                strand=strand,
                                frame=(frame + 1) * strand,
                                length=end - i,
                                protein="".join(protein_chars),
                                start_codon=codon,
                                stop_codon=stop_codon,
                                crosses_origin=crosses,
                            )
                        )
                        i = end if not require_start else i + 3
                        continue
                i += 3
    # keep the longest ORF per (strand, stop position)
    best: dict[tuple, ORF] = {}
    for orf in orfs:
        key = (orf.strand, orf.end)
        if key not in best or orf.length > best[key].length:
            best[key] = orf
    result = sorted(best.values(), key=lambda o: (-o.length, o.start))
    return result


def _find_all(haystack: str, needle: str) -> list[int]:
    out: list[int] = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return out
        out.append(idx)
        start = idx + 1


def annotate_sequence(
    sequence: str,
    *,
    circular: bool = False,
    extra_library: Iterable[dict] | None = None,
    include_orfs: bool = True,
    min_orf_aa: int = 80,
) -> list[Feature]:
    """Detect known elements (and optionally long ORFs) in a raw sequence."""
    seq = sequence.upper()
    n = len(seq)
    if n == 0:
        return []
    library = list(load_library()) + list(extra_library or [])
    search_space = seq + seq[: min(n, 2000)] if circular else seq
    found: list[Feature] = []
    seen: set[tuple] = set()

    for entry in library:
        sig = str(entry.get("signature", "")).upper()
        if not sig:
            continue
        span = int(entry.get("length") or len(sig))
        offset = int(entry.get("offset") or 0)
        for strand, probe in ((1, sig), (-1, reverse_complement(sig))):
            if strand == -1 and probe == sig:
                continue
            for hit in _find_all(search_space, probe):
                if hit >= n:
                    continue
                if strand == 1:
                    start = hit - offset
                    end = start + span
                else:
                    end = hit + len(probe) + offset
                    start = end - span
                if circular:
                    start %= n
                    end = start + min(span, n)
                else:
                    start = max(0, start)
                    end = min(n, end)
                if end <= start:
                    continue
                key = (entry.get("name"), start, end, strand)
                if key in seen:
                    continue
                seen.add(key)
                quals = {"label": entry.get("name"), "detected_by": "geneforge-autoannotate"}
                if entry.get("note"):
                    quals["note"] = entry["note"]
                found.append(
                    Feature(
                        type=entry.get("type", "misc_feature"),
                        segments=[(start, min(end, n))],
                        strand=strand,
                        name=str(entry.get("name") or "element"),
                        qualifiers=quals,
                        color=entry.get("color"),
                    )
                )

    if include_orfs:
        covered = [(f.start, f.end) for f in found if f.type == "CDS"]
        for orf in find_orfs(seq, min_aa=min_orf_aa, circular=circular)[:25]:
            if any(orf.start >= c[0] - 30 and orf.end <= c[1] + 30 for c in covered):
                continue
            found.append(
                Feature(
                    type="CDS",
                    segments=[(min(orf.start, orf.end), max(orf.start, orf.end))],
                    strand=orf.strand,
                    name=f"ORF {len(orf.protein)} aa",
                    qualifiers={
                        "label": f"ORF {len(orf.protein)} aa",
                        "translation": orf.protein,
                        "detected_by": "geneforge-orf-finder",
                        "codon_start": 1,
                    },
                    color="#4f8ef7",
                )
            )
    found.sort(key=lambda f: (f.start, -f.length))
    return found


def transfer_annotations(
    reference: SeqRecord,
    target_sequence: str,
    *,
    min_identity: float = 80.0,
) -> list[Feature]:
    """Map reference features onto a new sequence via pairwise alignment.

    Short constructs use the exact DP alignment and a per-base coordinate map.
    Long ones fall back to anchored chaining, where each matched block gives a
    constant offset — enough to carry curated maps onto sequencing assemblies.
    """
    result = align_pair(target_sequence, reference.sequence, mode="global")
    if result.identity < min_identity:
        return []

    ref_to_target: dict[int, int] = {}
    if result.aligned_query:
        qi, ti = result.query_start, result.target_start
        for q, t in zip(result.aligned_query, result.aligned_target, strict=True):
            if q != "-" and t != "-":
                ref_to_target[ti] = qi
            if q != "-":
                qi += 1
            if t != "-":
                ti += 1
        offsets: list[tuple[int, int, int]] = []
    else:
        # anchored result: (ref_start, ref_end, delta) per collinear block
        offsets = [
            (
                int(block["target_start"]),
                int(block["target_end"]),
                int(block["query_start"]) - int(block["target_start"]),
            )
            for block in result.blocks
        ]
        if not offsets:
            return []

    def map_position(ref_pos: int) -> int | None:
        if ref_to_target:
            return ref_to_target.get(ref_pos)
        for start, end, delta in offsets:
            if start <= ref_pos < end:
                return ref_pos + delta
        return None

    out: list[Feature] = []
    for feat in reference.features:
        segments = []
        for start, end in feat.segments:
            mapped = [p for p in (map_position(i) for i in range(start, end)) if p is not None]
            if len(mapped) < max(3, (end - start) * 0.5):
                continue
            segments.append((min(mapped), max(mapped) + 1))
        if not segments:
            continue
        out.append(
            Feature(
                type=feat.type,
                segments=segments,
                strand=feat.strand,
                name=feat.name,
                qualifiers={**feat.qualifiers, "transferred_from": reference.name},
                color=feat.color,
            )
        )
    return out


def sequence_statistics(sequence: str, *, circular: bool = False, table_id: int = 1) -> dict:
    seq = sequence.upper()
    orfs = find_orfs(seq, min_aa=50, circular=circular, table_id=table_id)
    return {
        "length": len(seq),
        "gc": gc_content(seq),
        "topology": "circular" if circular else "linear",
        "orf_count": len(orfs),
        "longest_orf": orfs[0].to_dict() if orfs else None,
        "a": seq.count("A"),
        "c": seq.count("C"),
        "g": seq.count("G"),
        "t": seq.count("T"),
        "ambiguous": sum(1 for ch in seq if ch not in "ACGT"),
        "first_frame_protein": translate(seq[:3000], table_id)[:1000],
    }


def library_entries() -> list[dict]:
    return load_library()
