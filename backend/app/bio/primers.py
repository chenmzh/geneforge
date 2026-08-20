"""Primer thermodynamics, primer design, PCR simulation and cloning primers.

Tm uses the SantaLucia (1998) unified nearest-neighbour parameters with the
monovalent-equivalent salt correction, which is what NEB/IDT calculators report,
so numbers here match what a wet-lab user expects.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .alphabet import UNAMBIGUOUS, gc_content, matches_iupac, reverse_complement

R_GAS = 1.9872  # cal/(mol*K)

# Default PCR buffer, used everywhere so designed / analysed / simulated Tm agree.
DEFAULT_PRIMER_CONC_NM = 500.0
DEFAULT_NA_MM = 50.0
DEFAULT_MG_MM = 1.5

# (dH kcal/mol, dS cal/(mol*K)) for the 10 unique NN pairs.
NN_PARAMS: dict[str, tuple[float, float]] = {
    "AA": (-7.9, -22.2), "TT": (-7.9, -22.2),
    "AT": (-7.2, -20.4),
    "TA": (-7.2, -21.3),
    "CA": (-8.5, -22.7), "TG": (-8.5, -22.7),
    "GT": (-8.4, -22.4), "AC": (-8.4, -22.4),
    "CT": (-7.8, -21.0), "AG": (-7.8, -21.0),
    "GA": (-8.2, -22.2), "TC": (-8.2, -22.2),
    "CG": (-10.6, -27.2),
    "GC": (-9.8, -24.4),
    "GG": (-8.0, -19.9), "CC": (-8.0, -19.9),
}
INIT_GC = (0.1, -2.8)
INIT_AT = (2.3, 4.1)


@dataclass
class PrimerStats:
    sequence: str
    length: int
    tm: float
    gc: float
    dh: float
    ds: float
    dg: float
    gc_clamp: bool
    max_homopolymer: int
    hairpin_score: float
    self_dimer_score: float
    end_stability: float
    degenerate: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__ | {"tm": round(self.tm, 2), "dg": round(self.dg, 2)}


def salt_corrected_na(na_mM: float, mg_mM: float, dntp_mM: float = 0.0) -> float:
    """Monovalent-equivalent sodium concentration in mol/L (long-duplex estimate)."""
    free_mg = max(0.0, mg_mM - dntp_mM)
    return max(1e-4, (na_mM + 120.0 * math.sqrt(free_mg)) / 1000.0)


def salt_correction(seq: str, *, na_mM: float, mg_mM: float, dntp_mM: float = 0.0) -> float:
    """Owczarzy (2004/2008) salt correction as a 1/Tm[K] offset.

    The unified nearest-neighbour parameters describe 1 M Na+, while real PCR
    buffers are ~50 mM Na+ plus 1.5-3 mM Mg2+, and Mg2+ dominates duplex
    stabilisation. Using the published divalent model instead of a crude
    monovalent equivalent keeps Tm within roughly 1 C of NEB/IDT calculators.
    """
    gc = gc_content(seq) / 100.0
    n = max(2, len(seq))
    mon = max(0.0, na_mM) / 1000.0
    mg = max(0.0, mg_mM - dntp_mM) / 1000.0

    def monovalent_only() -> float:
        if mon <= 0:
            return 0.0
        ln_mon = math.log(mon)
        return (4.29 * gc - 3.95) * 1e-5 * ln_mon + 9.40e-6 * ln_mon**2

    if mg <= 0:
        return monovalent_only()

    a, b, c, d = 3.92e-5, -9.11e-6, 6.26e-5, 1.42e-5
    e, f, g = -4.82e-4, 5.25e-4, 8.31e-5

    if mon > 0:
        ratio = math.sqrt(mg) / mon
        if ratio < 0.22:  # monovalent dominates
            return monovalent_only()
        if ratio < 6.0:  # mixed regime: re-parameterise a, d and g
            ln_mon = math.log(mon)
            a = 3.92e-5 * (0.843 - 0.352 * math.sqrt(mon) * ln_mon)
            d = 1.42e-5 * (1.279 - 4.03e-3 * ln_mon - 8.03e-3 * ln_mon**2)
            g = 8.31e-5 * (0.486 - 0.258 * ln_mon + 5.25e-3 * ln_mon**3)

    ln_mg = math.log(mg)
    return a + b * ln_mg + gc * (c + d * ln_mg) + (1.0 / (2.0 * (n - 1))) * (
        e + f * ln_mg + g * ln_mg**2
    )


def nn_thermo(seq: str) -> tuple[float, float]:
    """Return (dH kcal/mol, dS cal/mol/K) for a duplex."""
    seq = seq.upper()
    dh, ds = 0.0, 0.0
    init_first = INIT_GC if seq[0] in "GC" else INIT_AT
    init_last = INIT_GC if seq[-1] in "GC" else INIT_AT
    dh += init_first[0] + init_last[0]
    ds += init_first[1] + init_last[1]
    for i in range(len(seq) - 1):
        pair = seq[i : i + 2]
        params = NN_PARAMS.get(pair)
        if params is None:  # ambiguous base: use average stacking
            params = (-8.4, -22.4)
        dh += params[0]
        ds += params[1]
    return dh, ds


def melting_temp(
    seq: str,
    *,
    primer_conc_nM: float = DEFAULT_PRIMER_CONC_NM,
    na_mM: float = DEFAULT_NA_MM,
    mg_mM: float = DEFAULT_MG_MM,
    dntp_mM: float = 0.0,
) -> float:
    """Nearest-neighbour Tm in degrees Celsius (Owczarzy salt correction)."""
    seq = "".join(ch for ch in seq.upper() if ch.isalpha())
    if len(seq) < 2:
        return 0.0
    if len(seq) > 200:  # long duplex: the GC-based estimate is more appropriate
        na = salt_corrected_na(na_mM, mg_mM, dntp_mM)
        return round(
            81.5 + 16.6 * math.log10(na) + 0.41 * gc_content(seq) - 500.0 / len(seq), 2
        )
    dh, ds = nn_thermo(seq)
    ct = max(1e-12, primer_conc_nM * 1e-9)
    tm_1m = (dh * 1000.0) / (ds + R_GAS * math.log(ct / 4.0))  # Kelvin at 1 M Na+
    if tm_1m <= 0:
        return 0.0
    corrected = 1.0 / tm_1m + salt_correction(seq, na_mM=na_mM, mg_mM=mg_mM, dntp_mM=dntp_mM)
    if corrected <= 0:
        return 0.0
    return round(1.0 / corrected - 273.15, 2)


def free_energy(seq: str, temp_c: float = 37.0) -> float:
    dh, ds = nn_thermo(seq)
    return round(dh - (temp_c + 273.15) * ds / 1000.0, 2)


def max_homopolymer(seq: str) -> int:
    best, run = 1, 1
    for i in range(1, len(seq)):
        run = run + 1 if seq[i] == seq[i - 1] else 1
        best = max(best, run)
    return best if seq else 0


_PAIRS = {("A", "T"), ("T", "A"), ("G", "C"), ("C", "G")}


def _complement_score(a: str, b: str) -> float:
    """Score a stacked complementarity run: GC pairs weigh more than AT."""
    score = 0.0
    for x, y in zip(a, b, strict=False):
        if (x, y) in _PAIRS:
            score += 1.5 if x in "GC" else 1.0
        else:
            score -= 1.0
    return score


def worst_duplex(a: str, b: str) -> float:
    """Best (worst-case) complementarity between two oligos, sliding all offsets."""
    a, b = a.upper(), b.upper()
    best = 0.0
    for offset in range(-len(a) + 1, len(b)):
        run = 0.0
        local_best = 0.0
        for i in range(len(a)):
            j = offset + i
            if 0 <= j < len(b):
                x, y = a[i], b[j]
                if (x, y) in _PAIRS:
                    run += 1.5 if x in "GC" else 1.0
                    local_best = max(local_best, run)
                else:
                    run = max(0.0, run - 1.5)
        best = max(best, local_best)
    return round(best, 2)


def self_dimer_score(seq: str) -> float:
    return worst_duplex(seq, reverse_complement(seq))


def hairpin_score(seq: str, min_loop: int = 3, min_stem: int = 4) -> float:
    """Highest stem score of any hairpin with a loop of >= min_loop nt."""
    seq = seq.upper()
    n = len(seq)
    best = 0.0
    for loop_start in range(1, n):
        for loop_len in range(min_loop, n - loop_start + 1):
            left_end = loop_start
            right_start = loop_start + loop_len
            stem = min(left_end, n - right_start)
            if stem < min_stem:
                continue
            left = seq[left_end - stem : left_end]
            right = seq[right_start : right_start + stem]
            score = _complement_score(left[::-1], right)
            best = max(best, score)
    return round(best, 2)


def end_stability(seq: str, window: int = 5) -> float:
    """dG of the 3' terminal pentamer — low (more negative) means sticky 3' end."""
    tail = seq[-window:]
    return free_energy(tail) if len(tail) >= 2 else 0.0


def analyze_primer(
    seq: str,
    *,
    primer_conc_nM: float = DEFAULT_PRIMER_CONC_NM,
    na_mM: float = DEFAULT_NA_MM,
    mg_mM: float = DEFAULT_MG_MM,
) -> PrimerStats:
    seq = seq.upper().strip()
    warnings: list[str] = []
    if not seq:
        raise ValueError("Empty primer sequence")
    degenerate = any(ch not in UNAMBIGUOUS for ch in seq)
    tm = melting_temp(seq, primer_conc_nM=primer_conc_nM, na_mM=na_mM, mg_mM=mg_mM)
    gc = gc_content(seq)
    dh, ds = nn_thermo(seq)
    hp = hairpin_score(seq)
    sd = self_dimer_score(seq)
    homo = max_homopolymer(seq)
    clamp = seq[-1] in "GC"

    if len(seq) < 17:
        warnings.append("Primer shorter than 17 nt: specificity may be low")
    if len(seq) > 35:
        warnings.append("Primer longer than 35 nt: consider trimming")
    if gc < 35:
        warnings.append("GC content below 35%")
    if gc > 65:
        warnings.append("GC content above 65%")
    if homo >= 5:
        warnings.append(f"Homopolymer run of {homo} nt")
    if hp >= 8:
        warnings.append("Strong hairpin predicted")
    if sd >= 10:
        warnings.append("Strong self-dimer predicted")
    if not clamp:
        warnings.append("No G/C at the 3' end (weak GC clamp)")
    if seq[-5:].count("G") + seq[-5:].count("C") >= 4:
        warnings.append("GC-rich 3' end may cause mispriming")
    if degenerate:
        warnings.append("Primer contains degenerate bases")

    return PrimerStats(
        sequence=seq,
        length=len(seq),
        tm=tm,
        gc=gc,
        dh=round(dh, 2),
        ds=round(ds, 2),
        dg=free_energy(seq),
        gc_clamp=clamp,
        max_homopolymer=homo,
        hairpin_score=hp,
        self_dimer_score=sd,
        end_stability=end_stability(seq),
        degenerate=degenerate,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Primer pair design
# --------------------------------------------------------------------------- #
@dataclass
class DesignParams:
    min_len: int = 18
    max_len: int = 27
    opt_len: int = 20
    min_tm: float = 57.0
    max_tm: float = 65.0
    opt_tm: float = 60.0
    min_gc: float = 40.0
    max_gc: float = 60.0
    max_tm_diff: float = 3.0
    max_poly: int = 4
    search_window: int = 60
    product_min: int = 0
    product_max: int = 0
    primer_conc_nM: float = 500.0
    na_mM: float = 50.0
    mg_mM: float = DEFAULT_MG_MM


def _score_primer(stats: PrimerStats, params: DesignParams) -> float:
    score = 100.0
    score -= abs(stats.tm - params.opt_tm) * 3.0
    score -= abs(stats.length - params.opt_len) * 0.6
    if stats.gc < params.min_gc or stats.gc > params.max_gc:
        score -= 12.0
    score -= abs(stats.gc - 50.0) * 0.35
    if not stats.gc_clamp:
        score -= 6.0
    if stats.max_homopolymer > params.max_poly:
        score -= 8.0 * (stats.max_homopolymer - params.max_poly)
    score -= max(0.0, stats.hairpin_score - 6.0) * 2.0
    score -= max(0.0, stats.self_dimer_score - 8.0) * 1.5
    score += min(4.0, max(0.0, -stats.end_stability))
    return round(score, 2)


def _candidates(
    template: str,
    anchor: int,
    params: DesignParams,
    *,
    reverse: bool,
) -> list[dict]:
    """Candidate primers whose 3' end sits within the search window of ``anchor``."""
    out: list[dict] = []
    n = len(template)
    for shift in range(0, params.search_window + 1):
        for length in range(params.min_len, params.max_len + 1):
            if reverse:
                start = anchor + shift  # 3' end of the reverse primer (template coords)
                end = start + length
                if end > n:
                    continue
                seq = reverse_complement(template[start:end])
                binding = (start, end)
            else:
                end = anchor - shift
                start = end - length
                if start < 0:
                    continue
                seq = template[start:end]
                binding = (start, end)
            if any(ch not in UNAMBIGUOUS for ch in seq):
                continue
            stats = analyze_primer(
                seq,
                primer_conc_nM=params.primer_conc_nM,
                na_mM=params.na_mM,
                mg_mM=params.mg_mM,
            )
            if not (params.min_tm - 4 <= stats.tm <= params.max_tm + 4):
                continue
            out.append(
                {
                    "sequence": seq,
                    "start": binding[0],
                    "end": binding[1],
                    "strand": -1 if reverse else 1,
                    "stats": stats,
                    "score": _score_primer(stats, params),
                }
            )
    out.sort(key=lambda c: -c["score"])
    return out[:60]


def design_primer_pairs(
    template: str,
    target_start: int,
    target_end: int,
    *,
    params: DesignParams | None = None,
    max_pairs: int = 5,
) -> list[dict]:
    """Design primer pairs that amplify ``template[target_start:target_end]``."""
    params = params or DesignParams()
    template = template.upper()
    n = len(template)
    target_start = max(0, min(target_start, n))
    target_end = max(target_start + 1, min(target_end, n))

    forwards = _candidates(template, target_start + params.search_window // 3, params, reverse=False)
    reverses = _candidates(template, max(0, target_end - params.search_window // 3), params, reverse=True)

    pairs: list[dict] = []
    for fwd in forwards:
        for rev in reverses:
            if rev["end"] <= fwd["start"]:
                continue
            product_len = rev["end"] - fwd["start"]
            if params.product_min and product_len < params.product_min:
                continue
            if params.product_max and product_len > params.product_max:
                continue
            tm_diff = abs(fwd["stats"].tm - rev["stats"].tm)
            if tm_diff > params.max_tm_diff + 2:
                continue
            cross = worst_duplex(fwd["sequence"], reverse_complement(rev["sequence"]))
            covers = fwd["start"] <= target_start and rev["end"] >= target_end
            score = fwd["score"] + rev["score"] - tm_diff * 4.0 - max(0.0, cross - 9.0) * 2.0
            if covers:
                score += 15.0
            pairs.append(
                {
                    "forward": {
                        "name": "F",
                        "sequence": fwd["sequence"],
                        "start": fwd["start"],
                        "end": fwd["end"],
                        "strand": 1,
                        **fwd["stats"].to_dict(),
                    },
                    "reverse": {
                        "name": "R",
                        "sequence": rev["sequence"],
                        "start": rev["start"],
                        "end": rev["end"],
                        "strand": -1,
                        **rev["stats"].to_dict(),
                    },
                    "product_start": fwd["start"],
                    "product_end": rev["end"],
                    "product_size": product_len,
                    "product_gc": gc_content(template[fwd["start"] : rev["end"]]),
                    "tm_difference": round(tm_diff, 2),
                    "pair_dimer_score": cross,
                    "covers_target": covers,
                    "annealing_temp": round(min(fwd["stats"].tm, rev["stats"].tm) - 3.0, 1),
                    "score": round(score, 2),
                }
            )
    pairs.sort(key=lambda p: -p["score"])
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for pair in pairs:
        key = (pair["forward"]["sequence"], pair["reverse"]["sequence"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(pair)
        if len(deduped) >= max_pairs:
            break
    for i, pair in enumerate(deduped, start=1):
        pair["forward"]["name"] = f"F{i}"
        pair["reverse"]["name"] = f"R{i}"
    return deduped


def add_cloning_tails(
    pair: dict,
    *,
    fwd_tail: str = "",
    rev_tail: str = "",
    fwd_enzyme_site: str = "",
    rev_enzyme_site: str = "",
    spacer: str = "",
) -> dict:
    """Attach restriction/Gibson tails and recompute the full-oligo stats."""
    fwd = (fwd_tail + fwd_enzyme_site + spacer + pair["forward"]["sequence"]).upper()
    rev = (rev_tail + rev_enzyme_site + spacer + pair["reverse"]["sequence"]).upper()
    return {
        **pair,
        "forward_full": {"sequence": fwd, **analyze_primer(fwd).to_dict()},
        "reverse_full": {"sequence": rev, **analyze_primer(rev).to_dict()},
    }


def gibson_primers(
    insert: str,
    vector_left: str,
    vector_right: str,
    *,
    overlap: int = 25,
    params: DesignParams | None = None,
) -> dict:
    """Gibson/HiFi assembly primers: insert-specific core + vector homology arm."""
    params = params or DesignParams()
    insert = insert.upper()
    core_len = max(params.min_len, 20)
    fwd_core = insert[:core_len]
    rev_core = reverse_complement(insert[-core_len:])
    fwd = (vector_left[-overlap:] + fwd_core).upper()
    rev = (reverse_complement(vector_right[:overlap]) + rev_core).upper()
    return {
        "forward": {"sequence": fwd, "homology_arm": vector_left[-overlap:], "core": fwd_core, **analyze_primer(fwd_core).to_dict()},
        "reverse": {"sequence": rev, "homology_arm": reverse_complement(vector_right[:overlap]), "core": rev_core, **analyze_primer(rev_core).to_dict()},
        "overlap": overlap,
        "insert_length": len(insert),
    }


# --------------------------------------------------------------------------- #
# PCR simulation
# --------------------------------------------------------------------------- #
def find_binding_sites(
    template: str,
    primer: str,
    *,
    circular: bool = False,
    min_3prime_match: int = 12,
    max_mismatches: int = 3,
) -> list[dict]:
    """Locate primer binding sites: exact 3' anchor + tolerated 5' mismatches."""
    template = template.upper()
    primer = primer.upper()
    n = len(template)
    if not primer or n == 0:
        return []
    search = template + template[: len(primer)] if circular and n > len(primer) else template
    hits: list[dict] = []

    for strand in (1, -1):
        probe = primer if strand == 1 else reverse_complement(primer)
        anchor = probe[-min_3prime_match:] if strand == 1 else probe[:min_3prime_match]
        start_pos = 0
        while True:
            idx = search.find(anchor, start_pos)
            if idx < 0:
                break
            start_pos = idx + 1
            if strand == 1:
                bind_start = idx - (len(probe) - min_3prime_match)
                bind_end = bind_start + len(probe)
            else:
                bind_start = idx
                bind_end = idx + len(probe)
            if bind_start < 0 or bind_end > len(search):
                continue
            window = search[bind_start:bind_end]
            mismatches = sum(1 for a, b in zip(probe, window, strict=False) if not matches_iupac(a, b))
            if mismatches > max_mismatches:
                continue
            real_start = bind_start % n
            hits.append(
                {
                    "strand": strand,
                    "start": real_start,
                    "end": real_start + len(probe),
                    "mismatches": mismatches,
                    "tm": melting_temp(window),
                    "three_prime_pos": (bind_end - 1) % n if strand == 1 else real_start,
                    "matched": window,
                }
            )
    hits.sort(key=lambda h: (h["start"], h["strand"]))
    return hits


def simulate_pcr(
    template: str,
    forward: str,
    reverse: str,
    *,
    circular: bool = False,
    max_product: int = 20000,
    min_3prime_match: int = 12,
    max_mismatches: int = 3,
    max_sites: int = 200,
    max_products: int = 50,
) -> dict:
    """Predict PCR products (including origin-spanning ones on plasmids)."""
    template = template.upper()
    n = len(template)
    fwd_hits = [h for h in find_binding_sites(template, forward, circular=circular,
                                              min_3prime_match=min_3prime_match,
                                              max_mismatches=max_mismatches) if h["strand"] == 1]
    rev_hits = [h for h in find_binding_sites(template, reverse, circular=circular,
                                              min_3prime_match=min_3prime_match,
                                              max_mismatches=max_mismatches) if h["strand"] == -1]

    products: list[dict] = []
    truncated = False
    for f in fwd_hits[:max_sites]:
        for r in rev_hits[:max_sites]:
            f_start = f["start"]
            r_end = r["end"]
            if r_end > f_start:
                size = r_end - f_start
                crosses = False
                amplicon = template[f_start:r_end] if r_end <= n else (template[f_start:] + template[: r_end % n])
            elif circular:
                size = (r_end - f_start) % n
                crosses = True
                amplicon = template[f_start:] + template[: r_end % n]
            else:
                continue
            if not (0 < size <= max_product):
                continue
            full = (forward.upper() + amplicon[len(forward) : max(0, size - len(reverse))]
                    + reverse_complement(reverse.upper())) if size > len(forward) + len(reverse) else amplicon
            products.append(
                {
                    "start": f_start,
                    "end": r_end % n if crosses else r_end,
                    "size": size,
                    "crosses_origin": crosses,
                    "gc": gc_content(amplicon),
                    "tm_product": melting_temp(amplicon) if len(amplicon) > 1 else 0.0,
                    "forward_mismatches": f["mismatches"],
                    "reverse_mismatches": r["mismatches"],
                    "sequence": full[:max_product],
                }
            )
    products.sort(key=lambda p: p["size"])
    if len(products) > max_products:
        truncated = True
        products = products[:max_products]
    fwd_stats = analyze_primer(forward).to_dict() if forward else None
    rev_stats = analyze_primer(reverse).to_dict() if reverse else None
    ta = None
    if fwd_stats and rev_stats:
        ta = round(min(fwd_stats["tm"], rev_stats["tm"]) - 3.0, 1)
    warnings: list[str] = []
    if len(fwd_hits) > 1 or len(rev_hits) > 1:
        warnings.append(
            f"Multiple binding sites detected (forward: {len(fwd_hits)}, reverse: {len(rev_hits)}) — "
            "primers may be non-specific on this template"
        )
    if truncated:
        warnings.append(f"Product list truncated to {max_products} entries")
    if not products:
        warnings.append("No product predicted: check primer orientation, topology or mismatch tolerance")
    return {
        "forward": fwd_stats,
        "reverse": rev_stats,
        "forward_sites": fwd_hits[:max_sites],
        "reverse_sites": rev_hits[:max_sites],
        "forward_site_count": len(fwd_hits),
        "reverse_site_count": len(rev_hits),
        "products": products,
        "specific": len(products) == 1,
        "annealing_temp": ta,
        "warnings": warnings,
        "pair_dimer_score": worst_duplex(forward.upper(), reverse_complement(reverse.upper())) if forward and reverse else 0.0,
    }


def sequencing_primers(
    template: str,
    *,
    read_length: int = 800,
    spacing: int | None = None,
    params: DesignParams | None = None,
) -> list[dict]:
    """Tile primers along a template for full-length Sanger coverage."""
    params = params or DesignParams()
    spacing = spacing or max(300, read_length - 200)
    out: list[dict] = []
    for i, anchor in enumerate(range(0, max(1, len(template) - 100), spacing)):
        cands = _candidates(template, min(len(template) - 1, anchor + 40), params, reverse=False)
        if not cands:
            continue
        best = cands[0]
        out.append(
            {
                "name": f"seq_F{i + 1}",
                "sequence": best["sequence"],
                "start": best["start"],
                "end": best["end"],
                "strand": 1,
                "expected_coverage": [best["end"], min(len(template), best["end"] + read_length)],
                **best["stats"].to_dict(),
            }
        )
    return out
