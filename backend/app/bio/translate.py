"""Codon tables, translation and six-frame utilities."""
from __future__ import annotations

from .alphabet import reverse_complement

_BASES = "TCAG"
_AAS = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"

STANDARD_TABLE: dict[str, str] = {}
_i = 0
for _b1 in _BASES:
    for _b2 in _BASES:
        for _b3 in _BASES:
            STANDARD_TABLE[_b1 + _b2 + _b3] = _AAS[_i]
            _i += 1

# NCBI table 2 (vertebrate mitochondrial) differences
VERT_MITO_TABLE = dict(STANDARD_TABLE)
VERT_MITO_TABLE.update({"AGA": "*", "AGG": "*", "ATA": "M", "TGA": "W"})

# NCBI table 11 (bacterial/plant plastid) shares the standard mapping but has
# extra initiation codons; kept separate for start-codon aware ORF finding.
BACTERIAL_TABLE = dict(STANDARD_TABLE)

TABLES: dict[int, dict[str, str]] = {
    1: STANDARD_TABLE,
    2: VERT_MITO_TABLE,
    11: BACTERIAL_TABLE,
}

TABLE_NAMES = {1: "Standard", 2: "Vertebrate Mitochondrial", 11: "Bacterial / Plastid"}

START_CODONS = {1: ("ATG",), 2: ("ATG", "ATT", "ATC", "ATA", "GTG"), 11: ("ATG", "GTG", "TTG")}

AA_3LETTER = {
    "A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln",
    "E": "Glu", "G": "Gly", "H": "His", "I": "Ile", "L": "Leu", "K": "Lys",
    "M": "Met", "F": "Phe", "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp",
    "Y": "Tyr", "V": "Val", "*": "***", "X": "Xaa",
}

# Average residue masses (Da) for protein MW estimation.
AA_MASS = {
    "A": 71.08, "R": 156.19, "N": 114.10, "D": 115.09, "C": 103.14, "Q": 128.13,
    "E": 129.12, "G": 57.05, "H": 137.14, "I": 113.16, "L": 113.16, "K": 128.17,
    "M": 131.19, "F": 147.18, "P": 97.12, "S": 87.08, "T": 101.10, "W": 186.21,
    "Y": 163.18, "V": 99.13,
}


def get_table(table_id: int = 1) -> dict[str, str]:
    return TABLES.get(table_id, STANDARD_TABLE)


def translate(seq: str, table_id: int = 1, *, to_stop: bool = False) -> str:
    """Translate a nucleotide sequence in frame 0."""
    table = get_table(table_id)
    seq = seq.upper().replace("U", "T")
    out: list[str] = []
    for i in range(0, len(seq) - len(seq) % 3, 3):
        aa = table.get(seq[i : i + 3], "X")
        if aa == "*" and to_stop:
            break
        out.append(aa)
    return "".join(out)


def protein_mw(protein: str) -> float:
    return round(sum(AA_MASS.get(a, 110.0) for a in protein if a != "*") + 18.02, 2)


def isoelectric_point(protein: str) -> float:
    """Simple Bjellqvist-style bisection pI estimate."""
    pk = {"D": 3.65, "E": 4.25, "C": 8.18, "Y": 10.07, "H": 6.00, "K": 10.53, "R": 10.43}
    n_term, c_term = 9.69, 2.34
    counts = {a: protein.count(a) for a in pk}

    def charge(ph: float) -> float:
        c = 1.0 / (1.0 + 10 ** (ph - n_term)) - 1.0 / (1.0 + 10 ** (c_term - ph))
        for aa, p in pk.items():
            if aa in "KRH":
                c += counts[aa] / (1.0 + 10 ** (ph - p))
            else:
                c -= counts[aa] / (1.0 + 10 ** (p - ph))
        return c

    lo, hi = 0.0, 14.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if charge(mid) > 0:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 2)


def six_frame_translation(seq: str, table_id: int = 1) -> list[dict]:
    """Return the six reading frames, ready for the viewer's translation rows."""
    seq = seq.upper()
    rc = reverse_complement(seq)
    frames: list[dict] = []
    for frame in range(3):
        frames.append(
            {
                "frame": frame + 1,
                "strand": 1,
                "offset": frame,
                "protein": translate(seq[frame:], table_id),
            }
        )
    for frame in range(3):
        frames.append(
            {
                "frame": -(frame + 1),
                "strand": -1,
                "offset": frame,
                "protein": translate(rc[frame:], table_id),
            }
        )
    return frames


def codon_usage(seq: str) -> dict[str, int]:
    seq = seq.upper()
    usage: dict[str, int] = {}
    for i in range(0, len(seq) - len(seq) % 3, 3):
        codon = seq[i : i + 3]
        usage[codon] = usage.get(codon, 0) + 1
    return dict(sorted(usage.items(), key=lambda kv: -kv[1]))
