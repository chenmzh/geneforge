"""Nucleotide alphabet helpers: complement, IUPAC ambiguity, composition.

Pure standard library: the whole bio engine must run without third-party wheels
so the platform stays deployable in air-gapped lab environments.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

DNA_COMPLEMENT = str.maketrans(
    "ACGTURYSWKMBDHVNacgturyswkmbdhvn-",
    "TGCAAYRSWMKVHDBNtgcaayrswmkvhdbn-",
)

# Canonical IUPAC expansion used by enzyme-site and primer matching.
IUPAC: dict[str, str] = {
    "A": "A", "C": "C", "G": "G", "T": "T", "U": "T",
    "R": "AG", "Y": "CT", "S": "CG", "W": "AT", "K": "GT", "M": "AC",
    "B": "CGT", "D": "AGT", "H": "ACT", "V": "ACG", "N": "ACGT",
}

UNAMBIGUOUS = set("ACGT")
VALID_DNA = set(IUPAC.keys()) | {"-"}


def clean_sequence(seq: str, *, keep_gaps: bool = False) -> str:
    """Uppercase and strip everything that is not a nucleotide symbol."""
    if not seq:
        return ""
    seq = seq.upper()
    allowed = "ACGTURYSWKMBDHVN" + ("-" if keep_gaps else "")
    return "".join(ch for ch in seq if ch in allowed)


def is_valid_dna(seq: str) -> bool:
    return all(ch in VALID_DNA for ch in seq.upper())


def reverse_complement(seq: str) -> str:
    return seq.translate(DNA_COMPLEMENT)[::-1]


def complement(seq: str) -> str:
    return seq.translate(DNA_COMPLEMENT)


def gc_content(seq: str) -> float:
    seq = seq.upper()
    if not seq:
        return 0.0
    gc = sum(seq.count(b) for b in ("G", "C", "S"))
    return round(100.0 * gc / len(seq), 2)


def composition(seq: str) -> dict[str, int]:
    seq = seq.upper()
    counts = {b: seq.count(b) for b in ("A", "C", "G", "T")}
    counts["other"] = len(seq) - sum(counts.values())
    return counts


def molecular_weight(seq: str, *, double_stranded: bool = True) -> float:
    """Approximate MW in Da (sodium salt, linear dsDNA/ssDNA)."""
    mono = {"A": 313.21, "C": 289.18, "G": 329.21, "T": 304.20}
    ss = sum(mono.get(ch, 308.95) for ch in seq.upper()) + 79.0
    if not double_stranded:
        return round(ss, 2)
    rc = reverse_complement(seq)
    ss2 = sum(mono.get(ch, 308.95) for ch in rc) + 79.0
    return round(ss + ss2, 2)


def expand_ambiguous(pattern: str) -> str:
    """Turn an IUPAC pattern into an anchored-free regex body."""
    out = []
    for ch in pattern.upper():
        bases = IUPAC.get(ch)
        if bases is None:
            raise ValueError(f"Invalid IUPAC symbol: {ch!r}")
        out.append(bases[0] if len(bases) == 1 else f"[{bases}]")
    return "".join(out)


def compile_pattern(pattern: str) -> re.Pattern[str]:
    return re.compile(expand_ambiguous(pattern), re.IGNORECASE)


def matches_iupac(pattern: str, seq: str) -> bool:
    if len(pattern) != len(seq):
        return False
    return all(s in IUPAC.get(p, "") for p, s in zip(pattern.upper(), seq.upper(), strict=True))


def is_palindromic(site: str) -> bool:
    return site.upper() == reverse_complement(site.upper())


def windows(seq: str, size: int, step: int = 1) -> Iterable[tuple[int, str]]:
    for i in range(0, max(0, len(seq) - size + 1), step):
        yield i, seq[i : i + size]


def gc_skew_track(seq: str, window: int = 200, step: int | None = None) -> list[dict]:
    """GC content track for plotting under the sequence/plasmid view."""
    if step is None:
        step = max(1, window // 2)
    track: list[dict] = []
    if len(seq) < window:
        return [{"start": 0, "end": len(seq), "gc": gc_content(seq)}]
    for i in range(0, len(seq) - window + 1, step):
        sub = seq[i : i + window]
        track.append({"start": i, "end": i + window, "gc": gc_content(sub)})
    return track
