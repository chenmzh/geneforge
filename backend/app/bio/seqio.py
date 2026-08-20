"""Sequence I/O: FASTA, GenBank, EMBL(read), plain text and SnapGene ``.dna``.

The importer is intentionally permissive (labs feed us messy files) while the
exporter is strict so round-tripping through GeneForge produces files that
SnapGene, Benchling and Biopython all accept.
"""
from __future__ import annotations

import io
import re
import textwrap
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .alphabet import clean_sequence

FeatureSegment = tuple[int, int]

DEFAULT_COLORS = {
    "CDS": "#4f8ef7",
    "gene": "#5bc0a8",
    "promoter": "#f5a623",
    "terminator": "#d0021b",
    "rep_origin": "#9b59b6",
    "primer_bind": "#16a085",
    "misc_feature": "#7f8c8d",
    "RBS": "#e67e22",
    "polyA_signal": "#c0392b",
    "protein_bind": "#8e44ad",
    "LTR": "#2c3e50",
    "oriT": "#9b59b6",
    "source": "#bdc3c7",
    "regulatory": "#f39c12",
    "tRNA": "#1abc9c",
    "rRNA": "#1abc9c",
    "sig_peptide": "#e84393",
}

NAME_QUALIFIERS = ("label", "gene", "product", "standard_name", "note", "locus_tag", "bound_moiety")


@dataclass
class Feature:
    """A single annotation. Coordinates are 0-based half-open, like Python slices."""

    type: str = "misc_feature"
    start: int = 0
    end: int = 0
    strand: int = 1
    name: str = ""
    qualifiers: dict[str, Any] = field(default_factory=dict)
    segments: list[FeatureSegment] = field(default_factory=list)
    color: str | None = None

    def __post_init__(self) -> None:
        if not self.segments:
            self.segments = [(self.start, self.end)]
        else:
            self.start = min(s for s, _ in self.segments)
            self.end = max(e for _, e in self.segments)
        if not self.color:
            self.color = DEFAULT_COLORS.get(self.type, "#7f8c8d")
        if not self.name:
            for q in NAME_QUALIFIERS:
                if self.qualifiers.get(q):
                    val = self.qualifiers[q]
                    self.name = str(val[0] if isinstance(val, list) else val)[:120]
                    break
            else:
                self.name = self.type

    @property
    def length(self) -> int:
        return sum(e - s for s, e in self.segments)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "start": self.start,
            "end": self.end,
            "strand": self.strand,
            "name": self.name,
            "color": self.color,
            "qualifiers": self.qualifiers,
            "segments": [list(s) for s in self.segments],
        }


@dataclass
class SeqRecord:
    name: str = "unnamed"
    sequence: str = ""
    description: str = ""
    topology: str = "linear"  # linear | circular
    molecule_type: str = "ds-DNA"
    features: list[Feature] = field(default_factory=list)
    annotations: dict[str, Any] = field(default_factory=dict)
    source_format: str = "unknown"

    @property
    def length(self) -> int:
        return len(self.sequence)

    @property
    def is_circular(self) -> bool:
        return self.topology.lower().startswith("circ")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "length": self.length,
            "topology": self.topology,
            "molecule_type": self.molecule_type,
            "sequence": self.sequence,
            "features": [f.to_dict() for f in self.features],
            "annotations": self.annotations,
            "source_format": self.source_format,
        }


class SequenceParseError(ValueError):
    """Raised when no parser can make sense of the payload."""


# --------------------------------------------------------------------------- #
# FASTA
# --------------------------------------------------------------------------- #
def parse_fasta(text: str) -> list[SeqRecord]:
    records: list[SeqRecord] = []
    name, desc, chunks = None, "", []

    def flush() -> None:
        if name is not None:
            records.append(
                SeqRecord(
                    name=name,
                    description=desc,
                    sequence=clean_sequence("".join(chunks)),
                    source_format="fasta",
                )
            )

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith((">", ";")):
            if line.startswith(";"):
                continue
            flush()
            header = line[1:].strip()
            parts = header.split(None, 1)
            name = parts[0] if parts else "unnamed"
            desc = parts[1] if len(parts) > 1 else ""
            chunks = []
        else:
            chunks.append(line)
    flush()
    if not records:
        raise SequenceParseError("No FASTA records found")
    return records


def write_fasta(records: Sequence[SeqRecord], width: int = 70) -> str:
    out = io.StringIO()
    for rec in records:
        header = rec.name + (f" {rec.description}" if rec.description else "")
        out.write(f">{header}\n")
        for i in range(0, len(rec.sequence), width):
            out.write(rec.sequence[i : i + width] + "\n")
    return out.getvalue()


# --------------------------------------------------------------------------- #
# GenBank
# --------------------------------------------------------------------------- #
_LOC_RANGE = re.compile(r"^<?(\d+)(?:\.\.|\^)?>?(?:<?(\d+)>?)?$")


def _parse_location(loc: str) -> tuple[list[FeatureSegment], int]:
    """Parse a GenBank location string into 0-based half-open segments."""
    loc = loc.replace(" ", "")
    strand = 1
    while True:
        if loc.startswith("complement(") and loc.endswith(")"):
            strand = -strand
            loc = loc[len("complement(") : -1]
        elif loc.startswith(("join(", "order(", "bond(")) and loc.endswith(")"):
            inner = loc[loc.index("(") + 1 : -1]
            segments: list[FeatureSegment] = []
            depth, buf, parts = 0, "", []
            for ch in inner:
                if ch == "," and depth == 0:
                    parts.append(buf)
                    buf = ""
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                buf += ch
            if buf:
                parts.append(buf)
            sub_strand = strand
            for part in parts:
                segs, st = _parse_location(part)
                segments.extend(segs)
                if st == -1:
                    sub_strand = -abs(strand)
            segments.sort()
            return segments, sub_strand
        else:
            break

    loc = re.sub(r"^[A-Za-z0-9_.]+:", "", loc)  # drop remote accession refs
    m = _LOC_RANGE.match(loc)
    if not m:
        raise SequenceParseError(f"Unsupported GenBank location: {loc!r}")
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    if end < start:
        start, end = end, start
    return [(start - 1, end)], strand


def _clean_qualifier_value(value: str) -> Any:
    value = value.strip()
    if value.startswith('"') and value.endswith('"') and len(value) > 1:
        value = value[1:-1]
    return value.replace('""', '"')


def parse_genbank(text: str) -> list[SeqRecord]:
    records: list[SeqRecord] = []
    for block in re.split(r"^//\s*$", text, flags=re.MULTILINE):
        if not block.strip() or "LOCUS" not in block:
            continue
        records.append(_parse_genbank_record(block))
    if not records:
        raise SequenceParseError("No GenBank records found")
    return records


def _parse_genbank_record(block: str) -> SeqRecord:
    lines = block.splitlines()
    rec = SeqRecord(source_format="genbank")
    seq_chunks: list[str] = []
    section = None
    feature_lines: list[str] = []

    for line in lines:
        if not line.strip():
            continue
        keyword = line[:12].strip() if not line.startswith(" ") else ""
        if keyword == "LOCUS":
            parts = line.split()
            if len(parts) > 1:
                rec.name = parts[1]
            lower = line.lower()
            rec.topology = "circular" if "circular" in lower else "linear"
            mt = re.search(r"\b(ss|ds|ms)?-?(DNA|RNA|mRNA|cRNA)\b", line)
            if mt:
                rec.molecule_type = mt.group(0)
            section = "locus"
            continue
        if keyword == "DEFINITION":
            rec.description = line[12:].strip()
            section = "definition"
            continue
        if keyword in ("ACCESSION", "VERSION", "KEYWORDS", "SOURCE", "COMMENT"):
            rec.annotations[keyword.lower()] = line[12:].strip()
            section = keyword.lower()
            continue
        if keyword == "FEATURES":
            section = "features"
            continue
        if keyword == "ORIGIN":
            section = "origin"
            continue
        if keyword and keyword not in ("BASE",):
            section = "other"
            continue

        if section == "definition" and line.startswith(" " * 12):
            rec.description = (rec.description + " " + line.strip()).strip()
        elif section == "features":
            feature_lines.append(line)
        elif section == "origin":
            seq_chunks.append(re.sub(r"[\s\d]", "", line))
        elif section == "comment" and line.startswith(" "):
            rec.annotations["comment"] = (rec.annotations.get("comment", "") + " " + line.strip()).strip()

    rec.sequence = clean_sequence("".join(seq_chunks))
    rec.features = _parse_genbank_features(feature_lines, len(rec.sequence))
    return rec


def _parse_genbank_features(lines: Iterable[str], seq_len: int) -> list[Feature]:
    features: list[Feature] = []
    cur_type: str | None = None
    cur_loc: list[str] = []
    cur_quals: dict[str, Any] = {}
    pending_key: str | None = None

    def flush() -> None:
        nonlocal cur_type, cur_loc, cur_quals, pending_key
        if cur_type is None:
            return
        try:
            segments, strand = _parse_location("".join(cur_loc))
        except SequenceParseError:
            cur_type, cur_loc, cur_quals, pending_key = None, [], {}, None
            return
        segments = [(max(0, s), min(e, seq_len) if seq_len else e) for s, e in segments]
        segments = [(s, e) for s, e in segments if e > s]
        if segments:
            color = None
            for key in ("ApEinfo_fwdcolor", "ApEinfo_revcolor", "color", "Color"):
                if cur_quals.get(key):
                    val = cur_quals[key]
                    color = str(val[0] if isinstance(val, list) else val)
                    break
            features.append(
                Feature(type=cur_type, segments=segments, strand=strand, qualifiers=cur_quals, color=color)
            )
        cur_type, cur_loc, cur_quals, pending_key = None, [], {}, None

    for line in lines:
        if len(line) > 5 and line[5] != " " and not line[5:21].strip().startswith("/"):
            key = line[5:21].strip()
            if key:
                flush()
                cur_type = key
                cur_loc = [line[21:].strip()]
                continue
        body = line[21:].rstrip() if len(line) > 21 else line.strip()
        stripped = body.strip()
        if stripped.startswith("/"):
            pending_key = None
            if "=" in stripped:
                key, _, value = stripped[1:].partition("=")
                key = key.strip()
                raw = value.strip()
                multiline = raw.startswith('"') and not (raw.endswith('"') and len(raw) > 1)
                if multiline:
                    # opening quote only: drop it now, the closing quote is stripped later
                    val = raw[1:].replace('""', '"')
                    pending_key = key
                else:
                    val = _clean_qualifier_value(value)
                if key in cur_quals:
                    existing = cur_quals[key]
                    cur_quals[key] = (existing if isinstance(existing, list) else [existing]) + [val]
                else:
                    cur_quals[key] = val
            else:
                cur_quals[stripped[1:].strip()] = True
        elif pending_key:
            val = cur_quals.get(pending_key, "")
            joined = f"{val} {stripped}".strip()
            if joined.endswith('"'):
                joined = joined[:-1]
                cur_quals[pending_key] = joined
                pending_key = None
            else:
                cur_quals[pending_key] = joined
        elif cur_type and not cur_quals:
            cur_loc.append(stripped)
    flush()
    return features


def _format_location(feature: Feature) -> str:
    parts = [f"{s + 1}..{e}" if e - s > 1 else f"{s + 1}" for s, e in feature.segments]
    loc = parts[0] if len(parts) == 1 else f"join({','.join(parts)})"
    if feature.strand == -1:
        loc = f"complement({loc})"
    return loc


def write_genbank(rec: SeqRecord) -> str:
    out = io.StringIO()
    today = date.today().strftime("%d-%b-%Y").upper()
    topology = "circular" if rec.is_circular else "linear"
    div = rec.annotations.get("division", "SYN")
    out.write(
        f"LOCUS       {rec.name[:22]:<22} {rec.length} bp    {rec.molecule_type:<7} "
        f"{topology:<8} {div} {today}\n"
    )
    definition = rec.description or rec.name
    wrapped = textwrap.wrap(definition, width=67) or [""]
    out.write(f"DEFINITION  {wrapped[0]}\n")
    for cont in wrapped[1:]:
        out.write(f"            {cont}\n")
    out.write(f"ACCESSION   {rec.annotations.get('accession', '.')}\n")
    out.write(f"VERSION     {rec.annotations.get('version', '.')}\n")
    out.write(f"KEYWORDS    {rec.annotations.get('keywords', '.')}\n")
    out.write(f"SOURCE      {rec.annotations.get('source', 'synthetic DNA construct')}\n")
    out.write("  ORGANISM  " + str(rec.annotations.get("organism", "synthetic DNA construct")) + "\n")
    out.write("COMMENT     Exported by GeneForge\n")
    out.write("FEATURES             Location/Qualifiers\n")
    for feat in sorted(rec.features, key=lambda f: (f.start, -f.end)):
        out.write(f"     {feat.type[:15]:<16}{_format_location(feat)}\n")
        quals = dict(feat.qualifiers or {})
        if feat.name and not any(quals.get(q) for q in ("label", "gene", "product")):
            quals["label"] = feat.name
        if feat.color:
            quals.setdefault("ApEinfo_fwdcolor", feat.color)
            quals.setdefault("ApEinfo_revcolor", feat.color)
        for key, value in quals.items():
            values = value if isinstance(value, list) else [value]
            for val in values:
                if val is True:
                    out.write(f"                     /{key}\n")
                    continue
                text = str(val).replace('"', '""')
                line = f'/{key}="{text}"'
                for chunk in textwrap.wrap(line, width=58) or [line]:
                    out.write(" " * 21 + chunk + "\n")
    out.write("ORIGIN\n")
    seq = rec.sequence.lower()
    for i in range(0, len(seq), 60):
        block = seq[i : i + 60]
        groups = " ".join(block[j : j + 10] for j in range(0, len(block), 10))
        out.write(f"{i + 1:>9} {groups}\n")
    out.write("//\n")
    return out.getvalue()


# --------------------------------------------------------------------------- #
# EMBL (read-only, best effort)
# --------------------------------------------------------------------------- #
def parse_embl(text: str) -> list[SeqRecord]:
    records: list[SeqRecord] = []
    for block in text.split("//"):
        if "ID   " not in block:
            continue
        rec = SeqRecord(source_format="embl")
        seq_chunks: list[str] = []
        ft_lines: list[str] = []
        in_seq = False
        for line in block.splitlines():
            tag, body = line[:2], line[5:].rstrip()
            if tag == "ID":
                rec.name = body.split(";")[0].strip()
                rec.topology = "circular" if "circular" in body.lower() else "linear"
            elif tag == "DE":
                rec.description = (rec.description + " " + body.strip()).strip()
            elif tag == "FT":
                ft_lines.append("     " + line[5:])
            elif tag == "SQ":
                in_seq = True
            elif in_seq:
                seq_chunks.append(re.sub(r"[\s\d]", "", line))
        rec.sequence = clean_sequence("".join(seq_chunks))
        rec.features = _parse_genbank_features(ft_lines, len(rec.sequence))
        records.append(rec)
    if not records:
        raise SequenceParseError("No EMBL records found")
    return records


# --------------------------------------------------------------------------- #
# SnapGene .dna (segment based binary container)
# --------------------------------------------------------------------------- #
_SNAPGENE_DIRECTIONALITY = {"0": 0, "1": 1, "2": -1, "3": 0}


def parse_snapgene(data: bytes) -> list[SeqRecord]:
    if len(data) < 10 or data[0] != 0x09:
        raise SequenceParseError("Not a SnapGene .dna file")
    rec = SeqRecord(name="snapgene_import", source_format="snapgene")
    pos = 0
    seen_dna = False
    while pos + 5 <= len(data):
        seg_type = data[pos]
        seg_len = int.from_bytes(data[pos + 1 : pos + 5], "big")
        payload = data[pos + 5 : pos + 5 + seg_len]
        pos += 5 + seg_len
        if seg_type == 0x00 and payload:
            flags = payload[0]
            rec.sequence = clean_sequence(payload[1:].decode("ascii", "ignore"))
            rec.topology = "circular" if flags & 0x01 else "linear"
            seen_dna = True
        elif seg_type == 0x0A and payload:
            rec.features.extend(_snapgene_features(payload, len(rec.sequence)))
        elif seg_type == 0x05 and payload:
            rec.features.extend(_snapgene_primers(payload, len(rec.sequence)))
        elif seg_type == 0x06 and payload:
            rec.annotations.update(_snapgene_notes(payload))
    if not seen_dna:
        raise SequenceParseError("SnapGene file contains no DNA segment")
    if rec.annotations.get("description"):
        rec.description = str(rec.annotations["description"])[:500]
    return [rec]


def _xml_root(payload: bytes) -> ET.Element | None:
    try:
        return ET.fromstring(payload.decode("utf-8", "ignore"))
    except ET.ParseError:
        return None


def _snapgene_features(payload: bytes, seq_len: int) -> list[Feature]:
    root = _xml_root(payload)
    if root is None:
        return []
    features: list[Feature] = []
    for node in root.iter("Feature"):
        segments: list[FeatureSegment] = []
        color = None
        for seg in node.iter("Segment"):
            rng = seg.get("range", "")
            if "-" not in rng:
                continue
            a, _, b = rng.partition("-")
            try:
                start, end = int(a) - 1, int(b)
            except ValueError:
                continue
            segments.append((max(0, start), end))
            color = color or seg.get("color")
        if not segments:
            continue
        quals: dict[str, Any] = {}
        for q in node.iter("Q"):
            name = q.get("name")
            vnode = q.find("V")
            if name and vnode is not None:
                quals[name] = vnode.get("text") or vnode.get("int") or vnode.text or ""
        strand = _SNAPGENE_DIRECTIONALITY.get(node.get("directionality", "1"), 1)
        features.append(
            Feature(
                type=node.get("type", "misc_feature"),
                segments=segments,
                strand=strand,
                name=node.get("name", ""),
                qualifiers=quals,
                color=color,
            )
        )
    return features


def _snapgene_primers(payload: bytes, seq_len: int) -> list[Feature]:
    root = _xml_root(payload)
    if root is None:
        return []
    out: list[Feature] = []
    for node in root.iter("Primer"):
        for site in node.iter("BindingSite"):
            rng = site.get("location", "")
            if "-" not in rng:
                continue
            a, _, b = rng.partition("-")
            try:
                start, end = int(a), int(b) + 1
            except ValueError:
                continue
            strand = -1 if site.get("boundStrand") == "1" else 1
            out.append(
                Feature(
                    type="primer_bind",
                    segments=[(max(0, start), end)],
                    strand=strand,
                    name=node.get("name", "primer"),
                    qualifiers={"sequence": node.get("sequence", "")},
                    color="#16a085",
                )
            )
    return out


def _snapgene_notes(payload: bytes) -> dict[str, Any]:
    root = _xml_root(payload)
    if root is None:
        return {}
    notes: dict[str, Any] = {}
    for child in root:
        text = (child.text or "").strip()
        if text:
            notes[child.tag.lower()] = text[:2000]
    return notes


# --------------------------------------------------------------------------- #
# Format sniffing
# --------------------------------------------------------------------------- #
def detect_format(payload: bytes | str, filename: str | None = None) -> str:
    if isinstance(payload, bytes):
        if payload[:1] == b"\x09":
            return "snapgene"
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            text = payload.decode("latin-1", "ignore")
    else:
        text = payload
    head = text.lstrip()[:2000]
    if head.startswith(">"):
        return "fasta"
    if head.startswith("LOCUS") or re.search(r"^LOCUS\s", head, re.MULTILINE):
        return "genbank"
    if head.startswith("ID   ") or re.search(r"^ID\s{3}", head, re.MULTILINE):
        return "embl"
    if head.startswith("@"):
        return "fastq"
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    return {
        "fa": "fasta", "fas": "fasta", "fasta": "fasta", "fna": "fasta", "ffn": "fasta",
        "gb": "genbank", "gbk": "genbank", "genbank": "genbank", "ape": "genbank",
        "embl": "embl", "dna": "snapgene", "seq": "plain", "txt": "plain",
        "fastq": "fastq", "fq": "fastq",
    }.get(ext, "plain")


def parse_fastq(text: str) -> list[SeqRecord]:
    lines = [line for line in text.splitlines() if line.strip()]
    records: list[SeqRecord] = []
    for i in range(0, len(lines) - 3, 4):
        if not lines[i].startswith("@"):
            continue
        header = lines[i][1:].split(None, 1)
        records.append(
            SeqRecord(
                name=header[0],
                description=header[1] if len(header) > 1 else "",
                sequence=clean_sequence(lines[i + 1]),
                annotations={"quality": lines[i + 3]},
                source_format="fastq",
            )
        )
    if not records:
        raise SequenceParseError("No FASTQ records found")
    return records


def parse_any(payload: bytes | str, filename: str | None = None) -> list[SeqRecord]:
    """Parse any supported payload into records, sniffing the format."""
    fmt = detect_format(payload, filename)
    if fmt == "snapgene":
        data = payload if isinstance(payload, bytes) else payload.encode("latin-1")
        return parse_snapgene(data)
    text = payload.decode("utf-8", "ignore") if isinstance(payload, bytes) else payload
    if fmt == "fasta":
        return parse_fasta(text)
    if fmt == "genbank":
        return parse_genbank(text)
    if fmt == "embl":
        return parse_embl(text)
    if fmt == "fastq":
        return parse_fastq(text)

    # Plain text: only accept it when it really looks like a nucleotide sequence,
    # otherwise a pasted document would silently import as garbage DNA.
    letters = [ch for ch in text.upper() if ch.isalpha()]
    seq = clean_sequence(text)
    if not seq:
        raise SequenceParseError("Payload contains no recognisable nucleotide sequence")
    unambiguous = sum(1 for ch in seq if ch in "ACGTU")
    if not letters or unambiguous / len(letters) < 0.9:
        raise SequenceParseError(
            "Payload does not look like a nucleotide sequence "
            f"({unambiguous}/{len(letters)} characters are A/C/G/T/U). "
            "Supply FASTA, GenBank, EMBL, FASTQ or SnapGene .dna instead."
        )
    stem = (filename or "pasted_sequence").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return [SeqRecord(name=stem or "pasted_sequence", sequence=seq, source_format="plain")]


def serialize(rec: SeqRecord, fmt: str = "genbank") -> str:
    fmt = fmt.lower()
    if fmt in ("gb", "gbk", "genbank"):
        return write_genbank(rec)
    if fmt in ("fa", "fasta"):
        return write_fasta([rec])
    if fmt == "plain":
        return rec.sequence
    raise ValueError(f"Unsupported export format: {fmt}")
