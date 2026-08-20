"""Sequence I/O tests: parsing, round-tripping and format sniffing."""
from __future__ import annotations

import pytest

from app.bio import seqio

GENBANK = """LOCUS       pTEST                   60 bp    ds-DNA  circular SYN 01-JAN-2026
DEFINITION  Test construct for the parser
            with a wrapped definition line
ACCESSION   .
VERSION     .
KEYWORDS    test
SOURCE      synthetic DNA construct
  ORGANISM  synthetic DNA construct
FEATURES             Location/Qualifiers
     source          1..60
                     /organism="synthetic DNA construct"
     CDS             join(1..10,20..30)
                     /label="spliced cds"
                     /note="a note that is long enough to be wrapped by the
                     writer when exported again"
     promoter        complement(35..48)
                     /label="rev promoter"
                     /ApEinfo_fwdcolor="#ff8800"
     misc_feature    <1..>15
                     /label="fuzzy"
ORIGIN
        1 atgcatgcat gcatgcatgc atgcatgcat gcatgcatgc atgcatgcat gcatgcatgc
//
"""

FASTA = """>seq1 first record
ATGCATGCAT
GCATGCATGC
>seq2 second record
TTTTAAAACCCC
"""


def test_parse_genbank_basics():
    rec = seqio.parse_genbank(GENBANK)[0]
    assert rec.name == "pTEST"
    assert rec.length == 60
    assert rec.topology == "circular"
    assert rec.molecule_type == "ds-DNA"
    assert "wrapped definition line" in rec.description
    assert rec.annotations["keywords"] == "test"


def test_parse_genbank_locations():
    rec = seqio.parse_genbank(GENBANK)[0]
    by_name = {f.name: f for f in rec.features}
    assert by_name["spliced cds"].segments == [(0, 10), (19, 30)]
    assert by_name["rev promoter"].strand == -1
    assert by_name["rev promoter"].segments == [(34, 48)]
    assert by_name["fuzzy"].segments == [(0, 15)]
    assert by_name["rev promoter"].color == "#ff8800"


def test_multiline_qualifier_is_joined():
    rec = seqio.parse_genbank(GENBANK)[0]
    cds = next(f for f in rec.features if f.name == "spliced cds")
    assert "wrapped by the writer" in str(cds.qualifiers["note"])


def test_genbank_round_trip_is_stable():
    original = seqio.parse_genbank(GENBANK)[0]
    written = seqio.write_genbank(original)
    reparsed = seqio.parse_genbank(written)[0]
    assert reparsed.sequence == original.sequence
    assert reparsed.topology == original.topology
    # the writer emits features in coordinate order, so compare as sets
    assert sorted((f.type, tuple(f.segments), f.strand, f.name) for f in reparsed.features) == sorted(
        (f.type, tuple(f.segments), f.strand, f.name) for f in original.features
    )
    # and a second pass must be byte-identical (idempotent writer)
    assert seqio.write_genbank(reparsed) == written


def test_fasta_multi_record():
    records = seqio.parse_fasta(FASTA)
    assert [r.name for r in records] == ["seq1", "seq2"]
    assert records[0].sequence == "ATGCATGCATGCATGCATGC"
    assert records[0].description == "first record"


def test_fasta_round_trip():
    records = seqio.parse_fasta(FASTA)
    again = seqio.parse_fasta(seqio.write_fasta(records))
    assert [r.sequence for r in again] == [r.sequence for r in records]


def test_detect_format():
    assert seqio.detect_format(GENBANK) == "genbank"
    assert seqio.detect_format(FASTA) == "fasta"
    assert seqio.detect_format("ATGCATGC", "x.txt") == "plain"
    assert seqio.detect_format(b"\x09\x00\x00\x00\x0eSnapGene") == "snapgene"
    assert seqio.detect_format("@read1\nACGT\n+\nIIII\n") == "fastq"


def test_parse_any_dispatches():
    assert seqio.parse_any(GENBANK)[0].name == "pTEST"
    assert seqio.parse_any(FASTA.encode())[0].name == "seq1"
    plain = seqio.parse_any("acgt acgt\nACGT", "raw_seq.txt")[0]
    assert plain.sequence == "ACGTACGTACGT"
    assert plain.name == "raw_seq"


def test_parse_any_rejects_garbage():
    with pytest.raises(seqio.SequenceParseError):
        seqio.parse_any("!!! not a sequence !!!", "x.txt")
    with pytest.raises(seqio.SequenceParseError):
        seqio.parse_any("Dear reviewer, please find the plasmid attached.", "note.txt")
    with pytest.raises(seqio.SequenceParseError):
        seqio.parse_any("", "empty.txt")


def test_parse_any_accepts_mostly_clean_dna_with_numbers():
    rec = seqio.parse_any("1 atgcatgcat 11 gcatgcatgc", "raw.txt")[0]
    assert rec.sequence == "ATGCATGCATGCATGCATGC"


def _snapgene_bytes(sequence: bytes, circular: bool, features_xml: bytes) -> bytes:
    def segment(kind: int, payload: bytes) -> bytes:
        return bytes([kind]) + len(payload).to_bytes(4, "big") + payload

    header = segment(9, b"\x00\x00SnapGene\x00\x01\x00\x0f\x00\x00")
    dna = segment(0, bytes([1 if circular else 0]) + sequence)
    feats = segment(10, features_xml)
    notes = segment(6, b"<Notes><Description>unit test</Description></Notes>")
    return header + dna + feats + notes


def test_parse_snapgene():
    xml = (
        b'<Features><Feature name="testfeat" type="CDS" directionality="2">'
        b'<Segment range="3-12" color="#ff0000" type="standard"/>'
        b'<Q name="note"><V text="hello"/></Q></Feature></Features>'
    )
    data = _snapgene_bytes(b"ATGCGATCGATCGAAATTTCCC", True, xml)
    rec = seqio.parse_snapgene(data)[0]
    assert rec.sequence == "ATGCGATCGATCGAAATTTCCC"
    assert rec.topology == "circular"
    assert rec.features[0].segments == [(2, 12)]
    assert rec.features[0].strand == -1  # directionality 2 = reverse
    assert rec.features[0].color == "#ff0000"
    assert rec.annotations["description"] == "unit test"


def test_snapgene_rejects_non_snapgene_payload():
    with pytest.raises(seqio.SequenceParseError):
        seqio.parse_snapgene(b"not a snapgene file at all")


def test_embl_reader():
    embl = """ID   TEST; SV 1; circular; DNA; STD; SYN; 24 BP.
DE   embl test record
FT   CDS             1..12
FT                   /label="cds"
SQ   Sequence 24 BP;
     atgcatgcatgc atgcatgcatgc                                              24
//
"""
    rec = seqio.parse_embl(embl)[0]
    assert rec.name == "TEST"
    assert rec.topology == "circular"
    assert rec.sequence == "ATGCATGCATGCATGCATGCATGC"
    assert rec.features[0].segments == [(0, 12)]


def test_serialize_rejects_unknown_format():
    rec = seqio.SeqRecord(name="x", sequence="ATGC")
    with pytest.raises(ValueError):
        seqio.serialize(rec, "vcf")
