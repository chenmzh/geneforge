"""Restriction enzyme catalogue and site search.

Cut offsets are stored REBASE-style as distances (in nt) from the first base of
the recognition site to the phosphodiester bond that is cleaved, on the top
strand (``fwd``) and bottom strand (``rev``).  Type IIS enzymes therefore have
offsets larger than the site length, and ``BmgBI`` style enzymes that cut inside
the site get offsets smaller than the site length.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from .alphabet import compile_pattern, is_palindromic, reverse_complement

# name: (site, fwd_cut, rev_cut, suppliers)
_RAW: dict[str, tuple] = {
    "AatII": ("GACGTC", 5, 1, "N"),
    "Acc65I": ("GGTACC", 1, 5, "N"),
    "AclI": ("AACGTT", 2, 4, "N"),
    "AfeI": ("AGCGCT", 3, 3, "N"),
    "AflII": ("CTTAAG", 1, 5, "N"),
    "AgeI": ("ACCGGT", 1, 5, "N"),
    "AhdI": ("GACNNNNNGTC", 6, 5, "N"),
    "AleI": ("CACNNNNGTG", 5, 5, "N"),
    "AluI": ("AGCT", 2, 2, "N"),
    "AlwNI": ("CAGNNNCTG", 6, 3, "N"),
    "ApaI": ("GGGCCC", 5, 1, "N"),
    "ApaLI": ("GTGCAC", 1, 5, "N"),
    "ApoI": ("RAATTY", 1, 5, "N"),
    "AscI": ("GGCGCGCC", 2, 6, "N"),
    "AseI": ("ATTAAT", 2, 4, "N"),
    "AsiSI": ("GCGATCGC", 5, 3, "N"),
    "AvaI": ("CYCGRG", 1, 5, "N"),
    "AvrII": ("CCTAGG", 1, 5, "N"),
    "BaeGI": ("GKGCMC", 5, 1, "N"),
    "BamHI": ("GGATCC", 1, 5, "N"),
    "BanI": ("GGYRCC", 1, 5, "N"),
    "BbsI": ("GAAGAC", 8, 12, "N"),
    "BciVI": ("GTATCC", 18, 16, "N"),
    "BclI": ("TGATCA", 1, 5, "N"),
    "BglI": ("GCCNNNNNGGC", 7, 4, "N"),
    "BglII": ("AGATCT", 1, 5, "N"),
    "BlpI": ("GCTNAGC", 2, 5, "N"),
    "BmgBI": ("CACGTC", 3, 3, "N"),
    "BmtI": ("GCTAGC", 5, 1, "N"),
    "BsaAI": ("YACGTR", 3, 3, "N"),
    "BsaBI": ("GATNNNNATC", 5, 5, "N"),
    "BsaHI": ("GRCGYC", 2, 4, "N"),
    "BsaI": ("GGTCTC", 7, 11, "N"),
    "BsaJI": ("CCNNGG", 1, 5, "N"),
    "BsaWI": ("WCCGGW", 1, 5, "N"),
    "BsmAI": ("GTCTC", 6, 10, "N"),
    "BsmBI": ("CGTCTC", 7, 11, "N"),
    "BsmI": ("GAATGC", 7, 5, "N"),
    "BsoBI": ("CYCGRG", 1, 5, "N"),
    "BspEI": ("TCCGGA", 1, 5, "N"),
    "BspHI": ("TCATGA", 1, 5, "N"),
    "BspMI": ("ACCTGC", 10, 14, "N"),
    "BspQI": ("GCTCTTC", 8, 11, "N"),
    "BsrBI": ("CCGCTC", 3, 3, "N"),
    "BsrGI": ("TGTACA", 1, 5, "N"),
    "BssHII": ("GCGCGC", 1, 5, "N"),
    "BssSI": ("CACGAG", 1, 5, "N"),
    "BstBI": ("TTCGAA", 2, 4, "N"),
    "BstEII": ("GGTNACC", 1, 6, "N"),
    "BstXI": ("CCANNNNNNTGG", 8, 4, "N"),
    "BstZ17I": ("GTATAC", 3, 3, "N"),
    "Bsu36I": ("CCTNAGG", 2, 5, "N"),
    "BtgI": ("CCRYGG", 1, 5, "N"),
    "BtgZI": ("GCGATG", 16, 20, "N"),
    "ClaI": ("ATCGAT", 2, 4, "N"),
    "CviQI": ("GTAC", 1, 3, "N"),
    "DdeI": ("CTNAG", 1, 4, "N"),
    "DpnI": ("GATC", 2, 2, "N"),
    "DraI": ("TTTAAA", 3, 3, "N"),
    "DraIII": ("CACNNNGTG", 6, 3, "N"),
    "DrdI": ("GACNNNNNNGTC", 7, 5, "N"),
    "EaeI": ("YGGCCR", 1, 5, "N"),
    "EagI": ("CGGCCG", 1, 5, "N"),
    "EarI": ("CTCTTC", 7, 10, "N"),
    "EciI": ("GGCGGA", 17, 15, "N"),
    "Eco53kI": ("GAGCTC", 3, 3, "N"),
    "EcoNI": ("CCTNNNNNAGG", 5, 6, "N"),
    "EcoO109I": ("RGGNCCY", 2, 5, "N"),
    "EcoRI": ("GAATTC", 1, 5, "N"),
    "EcoRV": ("GATATC", 3, 3, "N"),
    "Esp3I": ("CGTCTC", 7, 11, "T"),
    "FatI": ("CATG", 0, 4, "N"),
    "FauI": ("CCCGC", 9, 11, "N"),
    "Fnu4HI": ("GCNGC", 2, 3, "N"),
    "FokI": ("GGATG", 14, 18, "N"),
    "FseI": ("GGCCGGCC", 6, 2, "N"),
    "FspI": ("TGCGCA", 3, 3, "N"),
    "HaeII": ("RGCGCY", 5, 1, "N"),
    "HaeIII": ("GGCC", 2, 2, "N"),
    "HgaI": ("GACGC", 10, 15, "N"),
    "HhaI": ("GCGC", 3, 1, "N"),
    "HincII": ("GTYRAC", 3, 3, "N"),
    "HindIII": ("AAGCTT", 1, 5, "N"),
    "HinfI": ("GANTC", 1, 4, "N"),
    "HinP1I": ("GCGC", 1, 3, "N"),
    "HpaI": ("GTTAAC", 3, 3, "N"),
    "HpaII": ("CCGG", 1, 3, "N"),
    "HphI": ("GGTGA", 13, 12, "N"),
    "KasI": ("GGCGCC", 1, 5, "N"),
    "KpnI": ("GGTACC", 5, 1, "N"),
    "MboI": ("GATC", 0, 4, "N"),
    "MfeI": ("CAATTG", 1, 5, "N"),
    "MluI": ("ACGCGT", 1, 5, "N"),
    "MlyI": ("GAGTC", 10, 10, "N"),
    "MscI": ("TGGCCA", 3, 3, "N"),
    "MseI": ("TTAA", 1, 3, "N"),
    "MslI": ("CAYNNNNRTG", 5, 5, "N"),
    "MspA1I": ("CMGCKG", 3, 3, "N"),
    "NaeI": ("GCCGGC", 3, 3, "N"),
    "NarI": ("GGCGCC", 2, 4, "N"),
    "NciI": ("CCSGG", 2, 3, "N"),
    "NcoI": ("CCATGG", 1, 5, "N"),
    "NdeI": ("CATATG", 2, 4, "N"),
    "NgoMIV": ("GCCGGC", 1, 5, "N"),
    "NheI": ("GCTAGC", 1, 5, "N"),
    "NlaIII": ("CATG", 4, 0, "N"),
    "NlaIV": ("GGNNCC", 3, 3, "N"),
    "NotI": ("GCGGCCGC", 2, 6, "N"),
    "NruI": ("TCGCGA", 3, 3, "N"),
    "NsiI": ("ATGCAT", 5, 1, "N"),
    "NspI": ("RCATGY", 5, 1, "N"),
    "PacI": ("TTAATTAA", 5, 3, "N"),
    "PaqCI": ("CACCTGC", 11, 15, "N"),
    "PciI": ("ACATGT", 1, 5, "N"),
    "PflMI": ("CCANNNNNTGG", 7, 4, "N"),
    "PmlI": ("CACGTG", 3, 3, "N"),
    "PpuMI": ("RGGWCCY", 2, 5, "N"),
    "PshAI": ("GACNNNNGTC", 5, 5, "N"),
    "PsiI": ("TTATAA", 3, 3, "N"),
    "PspOMI": ("GGGCCC", 1, 5, "N"),
    "PstI": ("CTGCAG", 5, 1, "N"),
    "PvuI": ("CGATCG", 4, 2, "N"),
    "PvuII": ("CAGCTG", 3, 3, "N"),
    "RsaI": ("GTAC", 2, 2, "N"),
    "RsrII": ("CGGWCCG", 2, 5, "N"),
    "SacI": ("GAGCTC", 5, 1, "N"),
    "SacII": ("CCGCGG", 4, 2, "N"),
    "SalI": ("GTCGAC", 1, 5, "N"),
    "SapI": ("GCTCTTC", 8, 11, "N"),
    "Sau3AI": ("GATC", 0, 4, "N"),
    "Sau96I": ("GGNCC", 1, 4, "N"),
    "SbfI": ("CCTGCAGG", 6, 2, "N"),
    "ScaI": ("AGTACT", 3, 3, "N"),
    "ScrFI": ("CCNGG", 2, 3, "N"),
    "SexAI": ("ACCWGGT", 1, 6, "N"),
    "SfaNI": ("GCATC", 10, 14, "N"),
    "SfcI": ("CTRYAG", 1, 5, "N"),
    "SfiI": ("GGCCNNNNNGGCC", 8, 5, "N"),
    "SfoI": ("GGCGCC", 3, 3, "N"),
    "SgrAI": ("CRCCGGYG", 2, 6, "N"),
    "SmaI": ("CCCGGG", 3, 3, "N"),
    "SmlI": ("CTYRAG", 1, 5, "N"),
    "SnaBI": ("TACGTA", 3, 3, "N"),
    "SpeI": ("ACTAGT", 1, 5, "N"),
    "SphI": ("GCATGC", 5, 1, "N"),
    "SrfI": ("GCCCGGGC", 4, 4, "T"),
    "SspI": ("AATATT", 3, 3, "N"),
    "StuI": ("AGGCCT", 3, 3, "N"),
    "StyI": ("CCWWGG", 1, 5, "N"),
    "SwaI": ("ATTTAAAT", 4, 4, "T"),
    "TaqI": ("TCGA", 1, 3, "N"),
    "TfiI": ("GAWTC", 1, 4, "N"),
    "TseI": ("GCWGC", 1, 4, "N"),
    "Tsp509I": ("AATT", 0, 4, "N"),
    "TspMI": ("CCCGGG", 1, 5, "N"),
    "Tth111I": ("GACNNNGTC", 4, 5, "N"),
    "XbaI": ("TCTAGA", 1, 5, "N"),
    "XcmI": ("CCANNNNNNNNNTGG", 8, 7, "N"),
    "XhoI": ("CTCGAG", 1, 5, "N"),
    "XmaI": ("CCCGGG", 1, 5, "N"),
    "XmnI": ("GAANNNNTTC", 5, 5, "N"),
    "ZraI": ("GACGTC", 3, 3, "N"),
}

# Curated "common cloning" set surfaced first in the UI.
COMMON_ENZYMES: tuple[str, ...] = (
    "EcoRI", "BamHI", "HindIII", "XhoI", "XbaI", "SalI", "PstI", "NotI", "NcoI",
    "NdeI", "KpnI", "SacI", "SmaI", "SpeI", "SphI", "ApaI", "AvrII", "BglII",
    "EcoRV", "MluI", "NheI", "PvuII", "ScaI", "AgeI", "AscI", "AsiSI", "BsaI",
    "BsmBI", "BbsI", "SapI", "PacI", "FseI", "SbfI", "AatII", "AflII", "ClaI",
)


@dataclass(frozen=True)
class Enzyme:
    name: str
    site: str
    fwd_cut: int
    rev_cut: int
    suppliers: str = ""

    @property
    def site_length(self) -> int:
        return len(self.site)

    @property
    def is_palindromic(self) -> bool:
        return is_palindromic(self.site)

    @property
    def overhang(self) -> str:
        if self.fwd_cut < self.rev_cut:
            return "5'"
        if self.fwd_cut > self.rev_cut:
            return "3'"
        return "blunt"

    @property
    def overhang_length(self) -> int:
        return abs(self.rev_cut - self.fwd_cut)

    @property
    def is_type_iis(self) -> bool:
        return self.fwd_cut > self.site_length or self.rev_cut > self.site_length

    def display_site(self) -> str:
        """REBASE-style representation: ``G^AATT_C``, ``CCC^GGG``, ``GGTCTC(1/5)``."""
        if 0 <= self.fwd_cut <= self.site_length and 0 <= self.rev_cut <= self.site_length:
            chars = list(self.site)
            if self.fwd_cut == self.rev_cut:  # blunt: a single cut mark
                chars.insert(self.fwd_cut, "^")
                return "".join(chars)
            # insert from the right so earlier offsets stay valid
            marks = sorted([(self.fwd_cut, "^"), (self.rev_cut, "_")], reverse=True)
            for pos, mark in marks:
                chars.insert(pos, mark)
            return "".join(chars)
        return f"{self.site}({self.fwd_cut - self.site_length}/{self.rev_cut - self.site_length})"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "site": self.site,
            "display_site": self.display_site(),
            "fwd_cut": self.fwd_cut,
            "rev_cut": self.rev_cut,
            "overhang": self.overhang,
            "overhang_length": self.overhang_length,
            "palindromic": self.is_palindromic,
            "type_iis": self.is_type_iis,
            "suppliers": self.suppliers,
            "common": self.name in COMMON_ENZYMES,
        }


ENZYMES: dict[str, Enzyme] = {
    name: Enzyme(name, site, fwd, rev, sup) for name, (site, fwd, rev, sup) in _RAW.items()
}

ENZYMES_LOWER = {name.lower(): enz for name, enz in ENZYMES.items()}


def get_enzyme(name: str) -> Enzyme | None:
    return ENZYMES_LOWER.get(name.strip().lower())


def resolve_enzymes(names: Iterable[str] | None = None, *, common_only: bool = False) -> list[Enzyme]:
    if names:
        resolved = [get_enzyme(n) for n in names]
        return [e for e in resolved if e is not None]
    if common_only:
        return [ENZYMES[n] for n in COMMON_ENZYMES if n in ENZYMES]
    return sorted(ENZYMES.values(), key=lambda e: e.name)


@dataclass
class Site:
    enzyme: str
    position: int  # 0-based index of the first base of the recognition site
    strand: int  # 1 top strand, -1 bottom strand, 0 palindromic
    cut_top: int  # 0-based index of the bond cleaved on the top strand
    cut_bottom: int
    site_seq: str
    overhang: str
    overhang_seq: str

    def to_dict(self) -> dict:
        return {
            "enzyme": self.enzyme,
            "position": self.position,
            "start": self.position,
            "end": self.position + len(self.site_seq),
            "strand": self.strand,
            "cut_top": self.cut_top,
            "cut_bottom": self.cut_bottom,
            "site_seq": self.site_seq,
            "overhang": self.overhang,
            "overhang_seq": self.overhang_seq,
        }


@lru_cache(maxsize=1024)
def _patterns(site: str) -> tuple:
    fwd = compile_pattern(site)
    rc = reverse_complement(site)
    rev = None if rc == site else compile_pattern(rc)
    return fwd, rev


def _overhang_seq(seq: str, cut_top: int, cut_bottom: int, circular: bool) -> str:
    lo, hi = sorted((cut_top, cut_bottom))
    n = len(seq)
    if lo == hi:
        return ""
    if circular:
        return "".join(seq[i % n] for i in range(lo, hi))
    return seq[max(0, lo) : min(n, hi)]


def find_sites(
    sequence: str,
    enzymes: Sequence[Enzyme | str] | None = None,
    *,
    circular: bool = False,
    common_only: bool = False,
) -> list[Site]:
    """Find every recognition site of ``enzymes`` in ``sequence``."""
    seq = sequence.upper()
    n = len(seq)
    if n == 0:
        return []
    resolved: list[Enzyme] = []
    for item in enzymes or resolve_enzymes(common_only=common_only):
        enz = get_enzyme(item) if isinstance(item, str) else item
        if enz:
            resolved.append(enz)

    results: list[Site] = []
    for enz in resolved:
        span = enz.site_length
        search_seq = seq + seq[: span - 1] if circular and n > span else seq
        fwd_re, rev_re = _patterns(enz.site)
        for match in fwd_re.finditer(search_seq):
            pos = match.start()
            if pos >= n:
                continue
            cut_top, cut_bottom = pos + enz.fwd_cut, pos + enz.rev_cut
            if not circular and (min(cut_top, cut_bottom) < 0 or max(cut_top, cut_bottom) > n):
                continue
            results.append(
                Site(
                    enzyme=enz.name,
                    position=pos,
                    strand=0 if enz.is_palindromic else 1,
                    cut_top=cut_top % n if circular else cut_top,
                    cut_bottom=cut_bottom % n if circular else cut_bottom,
                    site_seq=match.group(0),
                    overhang=enz.overhang,
                    overhang_seq=_overhang_seq(seq, cut_top, cut_bottom, circular),
                )
            )
        if rev_re is not None:
            for match in rev_re.finditer(search_seq):
                pos = match.start()
                if pos >= n:
                    continue
                cut_top = pos + span - enz.rev_cut
                cut_bottom = pos + span - enz.fwd_cut
                if not circular and (min(cut_top, cut_bottom) < 0 or max(cut_top, cut_bottom) > n):
                    continue
                results.append(
                    Site(
                        enzyme=enz.name,
                        position=pos,
                        strand=-1,
                        cut_top=cut_top % n if circular else cut_top,
                        cut_bottom=cut_bottom % n if circular else cut_bottom,
                        site_seq=match.group(0),
                        overhang=enz.overhang,
                        overhang_seq=_overhang_seq(seq, cut_top, cut_bottom, circular),
                    )
                )
    results.sort(key=lambda s: (s.position, s.enzyme))
    return results


def site_summary(sites: Sequence[Site]) -> list[dict]:
    """Group sites per enzyme, the way SnapGene's enzyme panel does."""
    grouped: dict[str, list[Site]] = {}
    for site in sites:
        grouped.setdefault(site.enzyme, []).append(site)
    out: list[dict] = []
    for name, group in grouped.items():
        enz = ENZYMES[name]
        out.append(
            {
                "enzyme": name,
                "site": enz.site,
                "display_site": enz.display_site(),
                "overhang": enz.overhang,
                "count": len(group),
                "positions": [s.position for s in group],
                "cut_positions": [s.cut_top for s in group],
                "unique": len(group) == 1,
                "common": name in COMMON_ENZYMES,
            }
        )
    out.sort(key=lambda item: (item["count"], item["enzyme"]))
    return out


def unique_cutters(sequence: str, *, circular: bool = False, common_only: bool = True) -> list[dict]:
    sites = find_sites(sequence, circular=circular, common_only=common_only)
    return [row for row in site_summary(sites) if row["unique"]]


def non_cutters(sequence: str, *, circular: bool = False, common_only: bool = True) -> list[str]:
    sites = find_sites(sequence, circular=circular, common_only=common_only)
    cutting = {s.enzyme for s in sites}
    pool = resolve_enzymes(common_only=common_only)
    return sorted(e.name for e in pool if e.name not in cutting)
