"""Restriction digestion, virtual gel simulation and overhang compatibility."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .alphabet import gc_content, reverse_complement
from .enzymes import Enzyme, Site, find_sites, get_enzyme, resolve_enzymes


@dataclass
class Fragment:
    start: int
    end: int
    length: int
    sequence: str
    left_enzyme: str | None
    right_enzyme: str | None
    left_overhang: str
    right_overhang: str
    crosses_origin: bool = False

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "length": self.length,
            "gc": gc_content(self.sequence),
            "left_enzyme": self.left_enzyme,
            "right_enzyme": self.right_enzyme,
            "left_overhang": self.left_overhang,
            "right_overhang": self.right_overhang,
            "crosses_origin": self.crosses_origin,
            "sequence_preview": (
                self.sequence if self.length <= 120 else f"{self.sequence[:60]}...{self.sequence[-60:]}"
            ),
        }


def _cut_map(sites: Sequence[Site]) -> dict[int, Site]:
    """One representative site per top-strand cut position."""
    out: dict[int, Site] = {}
    for site in sites:
        out.setdefault(site.cut_top, site)
    return out


def digest(
    sequence: str,
    enzyme_names: Sequence[str],
    *,
    circular: bool = False,
) -> dict:
    """Perform a (multi-)enzyme digest and return fragments plus per-enzyme stats."""
    seq = sequence.upper()
    n = len(seq)
    enzymes: list[Enzyme] = [e for e in (get_enzyme(name) for name in enzyme_names) if e]
    unknown = [name for name in enzyme_names if not get_enzyme(name)]
    sites = find_sites(seq, enzymes, circular=circular)
    cuts = _cut_map(sites)
    cut_positions = sorted(cuts)

    fragments: list[Fragment] = []
    if not cut_positions:
        fragments.append(
            Fragment(0, n, n, seq, None, None, "", "", crosses_origin=False)
        )
    elif circular:
        if len(cut_positions) == 1:
            pos = cut_positions[0]
            linear = seq[pos:] + seq[:pos]
            enz = cuts[pos].enzyme
            fragments.append(
                Fragment(pos, pos + n, n, linear, enz, enz,
                         cuts[pos].overhang_seq, cuts[pos].overhang_seq, crosses_origin=pos != 0)
            )
        else:
            for i, start in enumerate(cut_positions):
                end = cut_positions[(i + 1) % len(cut_positions)]
                if end > start:
                    sub = seq[start:end]
                    crosses = False
                else:
                    sub = seq[start:] + seq[:end]
                    crosses = True
                fragments.append(
                    Fragment(
                        start, start + len(sub), len(sub), sub,
                        cuts[start].enzyme, cuts[end].enzyme,
                        cuts[start].overhang_seq, cuts[end].overhang_seq,
                        crosses_origin=crosses,
                    )
                )
    else:
        bounds = [0] + cut_positions + [n]
        for i in range(len(bounds) - 1):
            start, end = bounds[i], bounds[i + 1]
            if end <= start:
                continue
            left = cuts.get(start)
            right = cuts.get(end)
            fragments.append(
                Fragment(
                    start, end, end - start, seq[start:end],
                    left.enzyme if left else None,
                    right.enzyme if right else None,
                    left.overhang_seq if left else "",
                    right.overhang_seq if right else "",
                )
            )

    per_enzyme: dict[str, int] = {}
    for site in sites:
        per_enzyme[site.enzyme] = per_enzyme.get(site.enzyme, 0) + 1

    return {
        "length": n,
        "topology": "circular" if circular else "linear",
        "enzymes": [e.to_dict() for e in enzymes],
        "unknown_enzymes": unknown,
        "sites": [s.to_dict() for s in sites],
        "cut_positions": cut_positions,
        "fragments": [f.to_dict() for f in fragments],
        "fragment_sizes": sorted((f.length for f in fragments), reverse=True),
        "site_counts": per_enzyme,
    }


LADDERS: dict[str, list[int]] = {
    "1kb": [10000, 8000, 6000, 5000, 4000, 3000, 2000, 1500, 1000, 500],
    "1kb_plus": [10000, 8000, 6000, 5000, 4000, 3500, 3000, 2500, 2000, 1500, 1000, 850, 650, 500, 400, 300, 200, 100],
    "100bp": [1500, 1000, 900, 800, 700, 600, 500, 400, 300, 200, 100],
    "lambda_hindiii": [23130, 9416, 6557, 4361, 2322, 2027, 564, 125],
}


def gel_simulation(
    fragment_sizes: Sequence[int],
    *,
    ladder: str = "1kb_plus",
    gel_percent: float = 1.0,
) -> dict:
    """Map fragment sizes onto a normalised 0..1 migration axis (log-linear)."""
    ladder_sizes = LADDERS.get(ladder, LADDERS["1kb_plus"])
    all_sizes = [s for s in list(fragment_sizes) + ladder_sizes if s > 0]
    if not all_sizes:
        return {"ladder": ladder, "lanes": []}
    top = max(all_sizes) * 1.15
    bottom = max(20, min(all_sizes) * 0.8)
    log_top, log_bottom = math.log10(top), math.log10(bottom)
    # Higher agarose percentage spreads small fragments further down the gel.
    gamma = max(0.6, min(1.6, 1.0 / max(0.4, gel_percent)))

    def migration(size: int) -> float:
        if size <= 0:
            return 1.0
        frac = (log_top - math.log10(max(size, bottom))) / max(1e-6, log_top - log_bottom)
        return round(min(1.0, max(0.0, frac ** gamma)), 4)

    def band(size: int, kind: str) -> dict:
        return {
            "size": size,
            "migration": migration(size),
            "intensity": round(min(1.0, 0.25 + math.log10(max(size, 30)) / 5), 3),
            "kind": kind,
        }

    return {
        "ladder": ladder,
        "gel_percent": gel_percent,
        "lanes": [
            {"name": f"Ladder ({ladder})", "bands": [band(s, "ladder") for s in ladder_sizes]},
            {"name": "Digest", "bands": [band(s, "sample") for s in sorted(fragment_sizes, reverse=True)]},
        ],
    }


def compatible_overhangs(a: str, b: str) -> bool:
    """True when two sticky ends can be ligated (b is the partner's overhang)."""
    if not a and not b:
        return True  # blunt/blunt
    if len(a) != len(b) or not a or not b:
        return False
    return a.upper() == reverse_complement(b.upper())


def ligation_matrix(fragments: Sequence[dict]) -> list[dict]:
    """Which fragment ends can be joined — the basis of the cloning simulator."""
    out: list[dict] = []
    for i, frag in enumerate(fragments):
        for j, other in enumerate(fragments):
            if i == j:
                continue
            if compatible_overhangs(frag.get("right_overhang", ""), other.get("left_overhang", "")):
                out.append(
                    {
                        "donor": i,
                        "acceptor": j,
                        "overhang": frag.get("right_overhang", ""),
                        "blunt": not frag.get("right_overhang"),
                    }
                )
    return out


def enzyme_pair_suggestions(
    sequence: str,
    *,
    circular: bool = False,
    insert_region: tuple[int, int] | None = None,
    common_only: bool = True,
) -> list[dict]:
    """Suggest enzyme pairs that cut once each, ideally flanking a target region."""
    sites = find_sites(sequence, resolve_enzymes(common_only=common_only), circular=circular)
    by_enzyme: dict[str, list[Site]] = {}
    for site in sites:
        by_enzyme.setdefault(site.enzyme, []).append(site)
    singles = {name: group[0] for name, group in by_enzyme.items() if len(group) == 1}
    names = sorted(singles)
    out: list[dict] = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            sa, sb = singles[a], singles[b]
            lo, hi = sorted((sa.cut_top, sb.cut_top))
            score = 0.0
            if sa.overhang != "blunt" and sb.overhang != "blunt":
                score += 2.0
            if sa.overhang_seq and sb.overhang_seq and sa.overhang_seq != sb.overhang_seq:
                score += 1.5  # directional cloning
            distance = hi - lo
            if insert_region:
                ins_start, ins_end = insert_region
                if lo <= ins_start and hi >= ins_end:
                    score += 3.0
                else:
                    continue
            if 20 <= distance <= 12000:
                score += 1.0
            out.append(
                {
                    "enzyme_a": a,
                    "enzyme_b": b,
                    "cut_a": sa.cut_top,
                    "cut_b": sb.cut_top,
                    "distance": distance,
                    "overhang_a": sa.overhang_seq,
                    "overhang_b": sb.overhang_seq,
                    "directional": bool(sa.overhang_seq and sb.overhang_seq and sa.overhang_seq != sb.overhang_seq),
                    "score": round(score, 2),
                }
            )
    out.sort(key=lambda r: (-r["score"], -r["distance"]))
    return out[:40]
