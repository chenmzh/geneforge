"""Pairwise and multiple sequence alignment.

Short inputs use exact affine-gap dynamic programming; long inputs fall back to a
k-mer anchored/chained strategy so aligning a 5 kb Sanger read against a 50 kb
construct stays interactive instead of exploding into a 250M-cell DP matrix.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .alphabet import reverse_complement

MAX_DP_CELLS = 6_000_000


@dataclass
class Variant:
    kind: str  # substitution | insertion | deletion
    ref_pos: int
    query_pos: int
    ref: str
    query: str

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class AlignmentResult:
    method: str
    mode: str
    score: float
    identity: float
    similarity: float
    gaps: int
    length: int
    aligned_query: str
    aligned_target: str
    midline: str
    query_start: int
    query_end: int
    target_start: int
    target_end: int
    strand: int = 1
    cigar: str = ""
    variants: list[Variant] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)

    def to_dict(self, *, max_alignment_chars: int = 200_000) -> dict:
        return {
            "method": self.method,
            "mode": self.mode,
            "score": self.score,
            "identity": self.identity,
            "similarity": self.similarity,
            "gaps": self.gaps,
            "length": self.length,
            "aligned_query": self.aligned_query[:max_alignment_chars],
            "aligned_target": self.aligned_target[:max_alignment_chars],
            "midline": self.midline[:max_alignment_chars],
            "truncated": len(self.aligned_query) > max_alignment_chars,
            "query_start": self.query_start,
            "query_end": self.query_end,
            "target_start": self.target_start,
            "target_end": self.target_end,
            "strand": self.strand,
            "cigar": self.cigar,
            "variants": [v.to_dict() for v in self.variants[:5000]],
            "variant_count": len(self.variants),
            "blocks": self.blocks,
        }


@dataclass
class ScoreScheme:
    match: int = 2
    mismatch: int = -3
    gap_open: int = -6
    gap_extend: int = -2


def _cigar(aq: str, at: str) -> str:
    ops: list[tuple[str, int]] = []
    for q, t in zip(aq, at, strict=True):
        op = "D" if q == "-" else "I" if t == "-" else "M"
        if ops and ops[-1][0] == op:
            ops[-1] = (op, ops[-1][1] + 1)
        else:
            ops.append((op, 1))
    return "".join(f"{count}{op}" for op, count in ops)


def _collect_variants(aq: str, at: str, q_offset: int, t_offset: int) -> list[Variant]:
    variants: list[Variant] = []
    qi, ti = q_offset, t_offset
    run: Variant | None = None
    for q, t in zip(aq, at, strict=True):
        if q == "-":
            if run and run.kind == "deletion" and run.ref_pos + len(run.ref) == ti:
                run.ref += t
            else:
                run = Variant("deletion", ti, qi, t, "")
                variants.append(run)
            ti += 1
        elif t == "-":
            if run and run.kind == "insertion" and run.query_pos + len(run.query) == qi:
                run.query += q
            else:
                run = Variant("insertion", ti, qi, "", q)
                variants.append(run)
            qi += 1
        else:
            if q.upper() != t.upper():
                variants.append(Variant("substitution", ti, qi, t, q))
            run = None
            qi += 1
            ti += 1
    return variants


def _stats(aq: str, at: str) -> tuple[float, float, int]:
    matches = sum(1 for q, t in zip(aq, at, strict=True) if q != "-" and t != "-" and q.upper() == t.upper())
    aligned = sum(1 for q, t in zip(aq, at, strict=True) if q != "-" and t != "-")
    gaps = sum(1 for q, t in zip(aq, at, strict=True) if q == "-" or t == "-")
    identity = round(100.0 * matches / max(1, aligned), 2)
    similarity = round(100.0 * matches / max(1, len(aq)), 2)
    return identity, similarity, gaps


def _midline(aq: str, at: str) -> str:
    return "".join(
        "|" if q != "-" and t != "-" and q.upper() == t.upper() else (" " if "-" in (q, t) else ".")
        for q, t in zip(aq, at, strict=True)
    )


def _dp_align(query: str, target: str, mode: str, scheme: ScoreScheme) -> AlignmentResult:
    """Affine-gap DP. mode: global | local | glocal (free end gaps on target)."""
    q, t = query.upper(), target.upper()
    n, m = len(q), len(t)
    neg = float("-inf")
    go, ge = scheme.gap_open, scheme.gap_extend

    # rows of the three states; pointers stored per cell (0=M,1=Ix,2=Iy)
    ptr_m = bytearray((n + 1) * (m + 1))
    ptr_x = bytearray((n + 1) * (m + 1))
    ptr_y = bytearray((n + 1) * (m + 1))

    prev_m = [neg] * (m + 1)
    prev_x = [neg] * (m + 1)
    prev_y = [neg] * (m + 1)
    prev_m[0] = 0.0
    if mode == "global":
        for j in range(1, m + 1):
            prev_y[j] = go + ge * (j - 1)
    elif mode == "glocal":
        # query must align end-to-end; leading/trailing target gaps are free
        for j in range(1, m + 1):
            prev_y[j] = 0.0
    else:  # local: every cell may start a fresh alignment
        for j in range(1, m + 1):
            prev_m[j] = 0.0

    best = (0.0, 0, 0) if mode == "local" else (neg, 0, 0)
    for i in range(1, n + 1):
        cur_m = [neg] * (m + 1)
        cur_x = [neg] * (m + 1)
        cur_y = [neg] * (m + 1)
        if mode in ("global", "glocal"):
            cur_x[0] = go + ge * (i - 1)
        else:  # local
            cur_m[0] = 0.0
        qi = q[i - 1]
        base = i * (m + 1)
        for j in range(1, m + 1):
            sub = scheme.match if qi == t[j - 1] else scheme.mismatch
            # M
            diag_best = prev_m[j - 1]
            src = 0
            if prev_x[j - 1] > diag_best:
                diag_best, src = prev_x[j - 1], 1
            if prev_y[j - 1] > diag_best:
                diag_best, src = prev_y[j - 1], 2
            val = diag_best + sub
            if mode == "local" and val < 0:
                val, src = 0.0, 3
            cur_m[j] = val
            ptr_m[base + j] = src
            # Ix (gap in target, consume query)
            open_x = prev_m[j] + go
            ext_x = prev_x[j] + ge
            if ext_x > open_x:
                cur_x[j], ptr_x[base + j] = ext_x, 1
            else:
                cur_x[j], ptr_x[base + j] = open_x, 0
            # Iy (gap in query, consume target)
            open_y = cur_m[j - 1] + go
            ext_y = cur_y[j - 1] + ge
            if ext_y > open_y:
                cur_y[j], ptr_y[base + j] = ext_y, 2
            else:
                cur_y[j], ptr_y[base + j] = open_y, 0
            if mode == "local" and cur_m[j] > best[0]:
                best = (cur_m[j], i, j)
        prev_m, prev_x, prev_y = cur_m, cur_x, cur_y

    if mode == "global":
        end_i, end_j = n, m
        score = max(prev_m[m], prev_x[m], prev_y[m])
        state = [prev_m[m], prev_x[m], prev_y[m]].index(score)
    elif mode == "glocal":
        # best cell in the final query row: the whole query is consumed
        end_j = max(range(m + 1), key=lambda j: prev_m[j])
        score, end_i, state = prev_m[end_j], n, 0
    else:
        score, end_i, end_j = best
        state = 0

    aq: list[str] = []
    at: list[str] = []
    i, j = end_i, end_j
    while i > 0 or j > 0:
        if mode == "local" and (i == 0 or j == 0):
            break
        if mode == "glocal" and i == 0:
            break
        idx = i * (m + 1) + j
        if state == 0:
            if i == 0:
                state = 2
                continue
            if j == 0:
                state = 1
                continue
            src = ptr_m[idx]
            if mode == "local" and src == 3:
                break
            aq.append(q[i - 1])
            at.append(t[j - 1])
            i, j = i - 1, j - 1
            state = src if src in (0, 1, 2) else 0
        elif state == 1:
            aq.append(q[i - 1])
            at.append("-")
            src = ptr_x[idx]
            i -= 1
            state = 0 if src == 0 else 1
        else:
            aq.append("-")
            at.append(t[j - 1])
            src = ptr_y[idx]
            j -= 1
            state = 0 if src == 0 else 2

    aligned_query = "".join(reversed(aq))
    aligned_target = "".join(reversed(at))
    q_start, t_start = i, j
    identity, similarity, gaps = _stats(aligned_query, aligned_target)
    return AlignmentResult(
        method="dp-affine",
        mode=mode,
        score=float(score),
        identity=identity,
        similarity=similarity,
        gaps=gaps,
        length=len(aligned_query),
        aligned_query=aligned_query,
        aligned_target=aligned_target,
        midline=_midline(aligned_query, aligned_target),
        query_start=q_start,
        query_end=end_i,
        target_start=t_start,
        target_end=end_j,
        cigar=_cigar(aligned_query, aligned_target),
        variants=_collect_variants(aligned_query, aligned_target, q_start, t_start),
        blocks=[{"query_start": q_start, "query_end": end_i, "target_start": t_start, "target_end": end_j, "identity": identity}],
    )


def _kmer_index(seq: str, k: int) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for i in range(len(seq) - k + 1):
        index.setdefault(seq[i : i + k], []).append(i)
    return index


def _anchored_align(query: str, target: str, k: int = 14) -> AlignmentResult:
    """Seed-and-chain alignment for long sequences (identity from matched blocks)."""
    q, t = query.upper(), target.upper()
    k = max(8, min(k, min(len(q), len(t)) // 2 or 8))
    index = _kmer_index(t, k)
    hits: list[tuple[int, int]] = []
    step = 1 if len(q) < 200_000 else 2
    for i in range(0, len(q) - k + 1, step):
        for j in index.get(q[i : i + k], ())[:12]:
            hits.append((i, j))
    if not hits:
        return AlignmentResult(
            method="anchored", mode="local", score=0.0, identity=0.0, similarity=0.0,
            gaps=0, length=0, aligned_query="", aligned_target="", midline="",
            query_start=0, query_end=0, target_start=0, target_end=0,
        )

    # Group by diagonal, merge consecutive hits into ungapped blocks.
    by_diag: dict[int, list[tuple[int, int]]] = {}
    for i, j in hits:
        by_diag.setdefault(j - i, []).append((i, j))
    blocks: list[dict] = []
    for diag, group in by_diag.items():
        group.sort()
        start_i, start_j = group[0]
        last_i = group[0][0]
        for i, j in group[1:]:
            if i - last_i <= k:
                last_i = i
                continue
            blocks.append({"query_start": start_i, "query_end": last_i + k, "target_start": start_j, "target_end": start_j + (last_i + k - start_i), "diag": diag})
            start_i, start_j, last_i = i, j, i
        blocks.append({"query_start": start_i, "query_end": last_i + k, "target_start": start_j, "target_end": start_j + (last_i + k - start_i), "diag": diag})

    # Chain blocks (LIS by query then target) to keep a consistent path.
    blocks.sort(key=lambda b: (b["query_start"], b["target_start"]))
    chain: list[dict] = []
    for block in blocks:
        if chain and block["target_start"] < chain[-1]["target_end"] - k:
            if (block["query_end"] - block["query_start"]) > (chain[-1]["query_end"] - chain[-1]["query_start"]):
                chain[-1] = block
            continue
        if chain and block["query_start"] < chain[-1]["query_end"] - k:
            continue
        chain.append(block)

    matched = 0
    for block in chain:
        span = block["query_end"] - block["query_start"]
        seg_q = q[block["query_start"] : block["query_end"]]
        seg_t = t[block["target_start"] : block["target_start"] + span]
        block["identity"] = round(
            100.0 * sum(1 for a, b in zip(seg_q, seg_t, strict=False) if a == b) / max(1, min(len(seg_q), len(seg_t))), 2
        )
        matched += sum(1 for a, b in zip(seg_q, seg_t, strict=False) if a == b)

    q_start = chain[0]["query_start"] if chain else 0
    q_end = chain[-1]["query_end"] if chain else 0
    t_start = chain[0]["target_start"] if chain else 0
    t_end = chain[-1]["target_end"] if chain else 0
    covered = sum(b["query_end"] - b["query_start"] for b in chain)
    identity = round(100.0 * matched / max(1, covered), 2)
    return AlignmentResult(
        method="anchored",
        mode="local",
        score=float(matched * 2),
        identity=identity,
        similarity=round(100.0 * covered / max(1, len(q)), 2),
        gaps=max(0, (q_end - q_start) - covered),
        length=covered,
        aligned_query="",
        aligned_target="",
        midline="",
        query_start=q_start,
        query_end=q_end,
        target_start=t_start,
        target_end=t_end,
        blocks=chain,
    )


def align_pair(
    query: str,
    target: str,
    *,
    mode: str = "global",
    scheme: ScoreScheme | None = None,
    try_reverse_complement: bool = True,
    max_cells: int = MAX_DP_CELLS,
) -> AlignmentResult:
    """Align two sequences, auto-selecting exact DP or anchored chaining."""
    scheme = scheme or ScoreScheme()
    query = "".join(ch for ch in query.upper() if ch.isalpha())
    target = "".join(ch for ch in target.upper() if ch.isalpha())
    if not query or not target:
        raise ValueError("Both sequences must be non-empty")

    def run(q: str) -> AlignmentResult:
        if len(q) * len(target) > max_cells:
            return _anchored_align(q, target)
        return _dp_align(q, target, mode, scheme)

    forward = run(query)
    if not try_reverse_complement:
        return forward
    rc = reverse_complement(query)
    reverse = run(rc)
    if reverse.score > forward.score * 1.02:
        reverse.strand = -1
        return reverse
    return forward


# --------------------------------------------------------------------------- #
# Multiple alignment (center-star progressive)
# --------------------------------------------------------------------------- #
def multiple_alignment(
    sequences: Sequence[dict],
    *,
    scheme: ScoreScheme | None = None,
    max_cells: int = MAX_DP_CELLS,
) -> dict:
    """Center-star MSA: align every sequence to the longest one, then merge gaps.

    ``sequences`` items: ``{"name": str, "sequence": str}``.
    """
    entries = [
        {"name": s.get("name") or f"seq{i + 1}", "sequence": "".join(c for c in s["sequence"].upper() if c.isalpha())}
        for i, s in enumerate(sequences)
        if s.get("sequence")
    ]
    if len(entries) < 2:
        raise ValueError("At least two sequences are required")
    ref_idx = max(range(len(entries)), key=lambda i: len(entries[i]["sequence"]))
    ref = entries[ref_idx]

    master_ref = ref["sequence"]
    rows: dict[str, str] = {ref["name"]: master_ref}
    order = [ref["name"]]

    for idx, entry in enumerate(entries):
        if idx == ref_idx:
            continue
        result = align_pair(
            entry["sequence"], ref["sequence"], mode="global",
            scheme=scheme, try_reverse_complement=False, max_cells=max_cells,
        )
        aq, at = result.aligned_query, result.aligned_target
        if not aq:  # anchored fallback: pad to reference length
            rows[entry["name"]] = entry["sequence"].ljust(len(master_ref), "-")[: len(master_ref)]
            order.append(entry["name"])
            continue
        new_master: list[str] = []
        new_row: list[str] = []
        others = {name: [] for name in rows}
        pos_in_master = 0
        # Build a map: ungapped ref position -> column index in current master
        ref_cols: list[int] = [c for c, ch in enumerate(master_ref) if ch != "-"]
        cursor = 0
        for q, t in zip(aq, at, strict=True):
            if t == "-":
                # insertion relative to reference: add a gap column everywhere
                col = ref_cols[cursor] if cursor < len(ref_cols) else len(master_ref)
                while pos_in_master < col:
                    new_master.append(master_ref[pos_in_master])
                    for name in others:
                        others[name].append(rows[name][pos_in_master])
                    new_row.append("-")
                    pos_in_master += 1
                new_master.append("-")
                for name in others:
                    others[name].append("-")
                new_row.append(q)
            else:
                col = ref_cols[cursor] if cursor < len(ref_cols) else len(master_ref) - 1
                while pos_in_master <= col and pos_in_master < len(master_ref):
                    new_master.append(master_ref[pos_in_master])
                    for name in others:
                        others[name].append(rows[name][pos_in_master])
                    new_row.append(q if pos_in_master == col else "-")
                    pos_in_master += 1
                cursor += 1
        while pos_in_master < len(master_ref):
            new_master.append(master_ref[pos_in_master])
            for name in others:
                others[name].append(rows[name][pos_in_master])
            new_row.append("-")
            pos_in_master += 1
        master_ref = "".join(new_master)
        for name in others:
            rows[name] = "".join(others[name])
        rows[entry["name"]] = "".join(new_row)
        order.append(entry["name"])

    width = max(len(r) for r in rows.values())
    for name in rows:
        rows[name] = rows[name].ljust(width, "-")

    consensus: list[str] = []
    conservation: list[float] = []
    for col in range(width):
        column = [rows[name][col] for name in order]
        bases = [c for c in column if c != "-"]
        if not bases:
            consensus.append("-")
            conservation.append(0.0)
            continue
        top = max(set(bases), key=bases.count)
        frac = bases.count(top) / len(column)
        consensus.append(top if frac >= 0.5 else "N")
        conservation.append(round(frac, 3))

    identity_matrix: list[dict] = []
    for i, a in enumerate(order):
        for b in order[i + 1 :]:
            pairs = [(x, y) for x, y in zip(rows[a], rows[b], strict=True) if x != "-" and y != "-"]
            same = sum(1 for x, y in pairs if x == y)
            identity_matrix.append(
                {"a": a, "b": b, "identity": round(100.0 * same / max(1, len(pairs)), 2)}
            )

    return {
        "reference": ref["name"],
        "width": width,
        "rows": [{"name": name, "aligned": rows[name]} for name in order],
        "consensus": "".join(consensus),
        "conservation": conservation,
        "identity_matrix": identity_matrix,
    }
