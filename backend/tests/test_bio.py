"""Bio engine unit tests — the scientific core, no database or HTTP involved."""
from __future__ import annotations

import pytest

from app.bio import edit, seqio
from app.bio.align import align_pair, multiple_alignment
from app.bio.alphabet import gc_content, reverse_complement
from app.bio.annotate import annotate_sequence, find_orfs
from app.bio.digest import compatible_overhangs, digest, gel_simulation
from app.bio.enzymes import ENZYMES, find_sites, get_enzyme, site_summary
from app.bio.primers import analyze_primer, design_primer_pairs, melting_temp, simulate_pcr
from app.bio.translate import six_frame_translation, translate

MCS = "AAGCTTGCATGCCTGCAGGTCGACTCTAGAGGATCCCCGGGTACCGAGCTCGAATTC"
EGFP_HEAD = "ATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTGCCCATCCTGGTCGAGCTGGACGGCGACGTAAACGGC"


# --------------------------------------------------------------------------- #
# alphabet / translation
# --------------------------------------------------------------------------- #
def test_reverse_complement_is_involutive_and_case_preserving():
    assert reverse_complement("GAATTC") == "GAATTC"  # palindrome
    assert reverse_complement(reverse_complement("ACGTRYKM")) == "ACGTRYKM"
    assert reverse_complement("acgt") == "acgt"
    assert reverse_complement("ATGCn") == "nGCAT"


def test_gc_content():
    assert gc_content("GCGC") == 100.0
    assert gc_content("ATAT") == 0.0
    assert gc_content("ATGC") == 50.0
    assert gc_content("") == 0.0


def test_translation_matches_known_protein():
    # first 25 codons of the EGFP CDS
    assert translate(EGFP_HEAD) == "MVSKGEELFTGVVPILVELDGDVNG"


def test_six_frames_have_expected_shape():
    frames = six_frame_translation("ATGGCGATTACCGGTTTACGCA")
    assert [f["frame"] for f in frames] == [1, 2, 3, -1, -2, -3]
    assert frames[0]["protein"].startswith("MAIT")


# --------------------------------------------------------------------------- #
# enzymes / digestion
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name,site,display",
    [
        ("EcoRI", "GAATTC", "G^AATT_C"),   # 5' overhang AATT
        ("SmaI", "CCCGGG", "CCC^GGG"),      # blunt: one cut mark
        ("KpnI", "GGTACC", "G_GTAC^C"),     # 3' overhang GTAC
        ("BsaI", "GGTCTC", "GGTCTC(1/5)"),  # Type IIS: cuts downstream
    ],
)
def test_enzyme_display_sites(name, site, display):
    enzyme = get_enzyme(name)
    assert enzyme is not None
    assert enzyme.site == site
    assert enzyme.display_site() == display


def test_catalogue_offsets_are_sane():
    for enzyme in ENZYMES.values():
        assert 0 <= enzyme.fwd_cut <= enzyme.site_length + 25
        assert 0 <= enzyme.rev_cut <= enzyme.site_length + 25
        assert set(enzyme.site) <= set("ACGTRYSWKMBDHVN")


def test_find_sites_in_mcs_is_ordered_and_complete():
    sites = find_sites(MCS, ["HindIII", "SphI", "PstI", "SalI", "XbaI", "BamHI", "SmaI", "KpnI", "SacI", "EcoRI"])
    names = [s.enzyme for s in sites]
    assert names == ["HindIII", "SphI", "PstI", "SalI", "XbaI", "BamHI", "SmaI", "KpnI", "SacI", "EcoRI"]
    ecori = next(s for s in sites if s.enzyme == "EcoRI")
    assert MCS[ecori.position : ecori.position + 6] == "GAATTC"
    assert ecori.cut_top == ecori.position + 1
    assert ecori.overhang_seq == "AATT"


def test_reverse_strand_sites_are_reported():
    # BsmI (GAATGC) is non-palindromic: place it on the bottom strand only
    seq = "TTTT" + reverse_complement("GAATGC") + "TTTT"
    sites = find_sites(seq, ["BsmI"])
    assert len(sites) == 1
    assert sites[0].strand == -1
    assert sites[0].position == 4


def test_circular_search_wraps_the_origin():
    seq = "AATTC" + "T" * 40 + "G"  # GAATTC spans the origin
    linear = find_sites(seq, ["EcoRI"], circular=False)
    circular = find_sites(seq, ["EcoRI"], circular=True)
    assert linear == []
    assert len(circular) == 1
    assert circular[0].position == len(seq) - 1


def test_digest_fragment_sizes_sum_to_length():
    circ = "GAATTC" + "A" * 100 + "GGATCC" + "T" * 50
    result = digest(circ, ["EcoRI", "BamHI"], circular=True)
    assert sum(result["fragment_sizes"]) == len(circ)
    assert len(result["fragments"]) == 2

    linear = digest(MCS, ["EcoRI", "BamHI"], circular=False)
    assert sum(linear["fragment_sizes"]) == len(MCS)
    assert len(linear["fragments"]) == 3


def test_uncut_sequence_returns_single_fragment():
    result = digest("A" * 200, ["EcoRI"], circular=False)
    assert result["fragment_sizes"] == [200]
    assert result["cut_positions"] == []


def test_digest_reports_unknown_enzymes():
    result = digest(MCS, ["EcoRI", "NotAnEnzyme"], circular=False)
    assert result["unknown_enzymes"] == ["NotAnEnzyme"]


def test_overhang_compatibility():
    assert compatible_overhangs("AATT", "AATT")  # EcoRI/EcoRI
    assert compatible_overhangs("", "")  # blunt/blunt
    assert not compatible_overhangs("AATT", "GATC")
    assert not compatible_overhangs("AATT", "")


def test_gel_simulation_orders_bands_by_size():
    gel = gel_simulation([5000, 1000, 200])
    sample = gel["lanes"][1]["bands"]
    assert [b["size"] for b in sample] == [5000, 1000, 200]
    assert sample[0]["migration"] < sample[-1]["migration"]


# --------------------------------------------------------------------------- #
# primers
# --------------------------------------------------------------------------- #
def test_melting_temp_matches_published_calculators():
    primer = "GTAAAACGACGGCCAGTGCCAAGCT"  # 25 nt, 56% GC
    # 50 mM Na+, no Mg2+, 0.5 uM oligo: IDT/NEB report ~64-65 C
    assert melting_temp(primer, na_mM=50, mg_mM=0) == pytest.approx(64.7, abs=1.5)
    # 1 M Na+ (the raw nearest-neighbour reference state) is much higher
    assert melting_temp(primer, na_mM=1000, mg_mM=0) == pytest.approx(80.4, abs=1.5)
    # Mg2+ stabilises the duplex (Owczarzy 2008 divalent correction)
    assert melting_temp(primer, na_mM=50, mg_mM=1.5) > melting_temp(primer, na_mM=50, mg_mM=0)
    # GC content and length both raise Tm
    assert melting_temp("AT") < melting_temp("GCGCGCGCGC") < melting_temp("GCGCGCGCGCGCGCGCGCGC")


def test_salt_correction_regimes():
    from app.bio.primers import salt_correction

    seq = "GTAAAACGACGGCCAGTGCCAAGCT"
    # no salt at all -> no correction; more salt -> smaller (less positive) offset
    assert salt_correction(seq, na_mM=0, mg_mM=0) == 0.0
    assert salt_correction(seq, na_mM=1000, mg_mM=0) < salt_correction(seq, na_mM=50, mg_mM=0)
    # dNTPs chelate Mg2+, so a high dNTP concentration reduces the divalent effect
    high_mg = salt_correction(seq, na_mM=50, mg_mM=2.0)
    chelated = salt_correction(seq, na_mM=50, mg_mM=2.0, dntp_mM=1.8)
    assert chelated > high_mg


def test_analyze_primer_flags_problems():
    bad = analyze_primer("AAAAAAAAAAAAAAAAAAAA")
    assert bad.gc == 0.0
    assert any("GC content" in w for w in bad.warnings)
    assert any("Homopolymer" in w for w in bad.warnings)
    good = analyze_primer("GTAAAACGACGGCCAGTGCC")
    assert good.gc_clamp is True


def test_design_and_pcr_agree(rng_template):
    pairs = design_primer_pairs(rng_template, 400, 900, max_pairs=3)
    assert pairs, "no primer pairs designed"
    best = pairs[0]
    assert best["covers_target"]
    assert abs(best["forward"]["tm"] - best["reverse"]["tm"]) <= 5
    sim = simulate_pcr(rng_template, best["forward"]["sequence"], best["reverse"]["sequence"])
    assert sim["specific"], sim["warnings"]
    assert sim["products"][0]["size"] == best["product_size"]
    # the Tm reported by design and by analysis must be identical (same buffer)
    assert sim["forward"]["tm"] == best["forward"]["tm"]


def test_pcr_detects_no_product_for_wrong_orientation(rng_template):
    fwd = rng_template[100:122]
    bad_rev = rng_template[300:322]  # same strand: cannot amplify
    sim = simulate_pcr(rng_template, fwd, bad_rev)
    assert sim["products"] == []
    assert any("No product" in w for w in sim["warnings"])


def test_pcr_across_the_origin_of_a_plasmid(rng_template):
    fwd = rng_template[-120:-98]
    rev = reverse_complement(rng_template[60:82])
    sim = simulate_pcr(rng_template, fwd, rev, circular=True)
    assert sim["products"], "expected an origin-spanning product"
    assert sim["products"][0]["crosses_origin"]
    assert sim["products"][0]["size"] == 202


# --------------------------------------------------------------------------- #
# alignment
# --------------------------------------------------------------------------- #
def test_global_alignment_identity_and_variants():
    a = "ATGGCGATTACCGGTTTACGCA"
    b = "ATGGCGTTTACCGGTTTACGCA"
    result = align_pair(a, b, mode="global", try_reverse_complement=False)
    assert result.identity == pytest.approx(95.45, abs=0.01)
    assert len(result.variants) == 1
    assert result.variants[0].kind == "substitution"
    assert result.variants[0].ref_pos == 6


def test_glocal_places_a_read_inside_the_reference(rng_template):
    read = list(rng_template[300:600])
    read[50] = "A" if read[50] != "A" else "C"
    del read[150:153]
    result = align_pair("".join(read), rng_template, mode="glocal", try_reverse_complement=False)
    assert result.target_start == 300
    assert result.identity > 99
    kinds = sorted({v.kind for v in result.variants})
    assert kinds == ["deletion", "substitution"]


def test_local_alignment_finds_exact_substring(rng_template):
    result = align_pair(rng_template[700:760], rng_template, mode="local", try_reverse_complement=False)
    assert result.identity == 100.0
    assert (result.target_start, result.target_end) == (700, 760)


def test_reverse_complement_orientation_is_detected(rng_template):
    read = reverse_complement(rng_template[200:400])
    result = align_pair(read, rng_template, mode="glocal")
    assert result.strand == -1
    assert result.target_start == 200


def test_anchored_fallback_for_long_inputs(rng_template):
    long_target = rng_template * 4
    result = align_pair(long_target[500:3000], long_target, mode="local", max_cells=1000)
    assert result.method == "anchored"
    assert result.identity > 90


def test_multiple_alignment_consensus():
    msa = multiple_alignment(
        [
            {"name": "s1", "sequence": "ATGGCGATTACCGGTTTACGCA"},
            {"name": "s2", "sequence": "ATGGCGTTTACCGGTTTACGCA"},
            {"name": "s3", "sequence": "ATGGCGATTACCGGTTACGCA"},
        ]
    )
    assert len(msa["rows"]) == 3
    assert all(len(row["aligned"]) == msa["width"] for row in msa["rows"])
    assert len(msa["consensus"]) == msa["width"]
    assert len(msa["identity_matrix"]) == 3


# --------------------------------------------------------------------------- #
# ORFs / annotation
# --------------------------------------------------------------------------- #
def test_find_orfs_picks_the_longest_frame():
    seq = "TTT" + "ATG" + "GCT" * 60 + "TAA" + "CCC"
    orfs = find_orfs(seq, min_aa=20)
    assert orfs[0].start == 3
    assert orfs[0].protein == "M" + "A" * 60  # ATG + 60x GCT
    assert orfs[0].stop_codon == "TAA"


def test_auto_annotation_detects_known_elements():
    seq = "TAATACGACTCACTATAG" + "GGAATTGTGAGCGGATAACAATT" + EGFP_HEAD + "A" * 600
    names = {f.name for f in annotate_sequence(seq, circular=True)}
    assert "T7 promoter" in names
    assert "lac operator" in names
    assert "EGFP" in names


def test_annotation_detects_reverse_strand_elements():
    seq = "A" * 100 + reverse_complement("TAATACGACTCACTATAG") + "A" * 100
    hits = [f for f in annotate_sequence(seq, include_orfs=False) if f.name == "T7 promoter"]
    assert len(hits) == 1
    assert hits[0].strand == -1


# --------------------------------------------------------------------------- #
# editing
# --------------------------------------------------------------------------- #
def test_insert_shifts_downstream_features():
    features = [seqio.Feature(type="CDS", segments=[(4, 8)], name="mid")]
    seq, feats, note = edit.insert_sequence("AAAAGGGGTTTT", features, 2, "CC")
    assert seq == "AACCAAGGGGTTTT"
    assert feats[0].segments == [(6, 10)]
    assert "Inserted 2 bp" in note


def test_insert_inside_a_feature_extends_it():
    features = [seqio.Feature(type="CDS", segments=[(2, 10)], name="cds")]
    _, feats, _ = edit.insert_sequence("AAAAGGGGTTTT", features, 5, "CCC")
    assert feats[0].segments == [(2, 13)]


def test_delete_truncates_and_drops_features():
    features = [
        seqio.Feature(type="CDS", segments=[(0, 4)], name="left"),
        seqio.Feature(type="CDS", segments=[(4, 8)], name="mid"),
        seqio.Feature(type="CDS", segments=[(8, 12)], name="right"),
    ]
    seq, feats, _ = edit.delete_range("AAAAGGGGTTTT", features, 4, 8)
    assert seq == "AAAATTTT"
    names = {f.name: f.segments for f in feats}
    assert "mid" not in names
    assert names["left"] == [(0, 4)]
    assert names["right"] == [(4, 8)]


def test_reverse_complement_flips_strand_and_coordinates():
    features = [seqio.Feature(type="CDS", segments=[(4, 8)], strand=1, name="f")]
    seq, feats, _ = edit.reverse_complement_all("AAAAGGGGTTTT", features)
    assert seq == "AAAACCCCTTTT"
    assert feats[0].segments == [(4, 8)]
    assert feats[0].strand == -1


def test_set_origin_splits_features_across_the_junction():
    features = [seqio.Feature(type="CDS", segments=[(4, 8)], name="f")]
    seq, feats, _ = edit.set_origin("AAAAGGGGTTTT", features, 6)
    assert seq == "GGTTTTAAAAGG"
    assert feats[0].segments == [(0, 2), (10, 12)]


def test_replace_range_updates_length():
    seq, _, note = edit.replace_range("AAAAGGGGTTTT", [], 4, 8, "CC")
    assert seq == "AAAACCTTTT"
    assert "Replaced 4 bp" in note
