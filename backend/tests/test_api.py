"""API tests: auth, RBAC, sequence lifecycle, tools and jobs."""
from __future__ import annotations

import io
import time


# --------------------------------------------------------------------------- #
# system / auth
# --------------------------------------------------------------------------- #
def test_health_and_capabilities(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"
    caps = client.get("/api/v1/capabilities").json()
    assert "genbank" in caps["import_formats"]
    assert caps["enzyme_catalogue_size"] > 100


def test_unauthenticated_access_is_rejected(client):
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/sequences/does-not-exist").status_code == 401


def test_login_rejects_bad_credentials(client):
    res = client.post("/api/v1/auth/login", json={"username": "admin@test.local", "password": "wrong"})
    assert res.status_code == 401
    assert res.json()["code"] == "unauthenticated"


def test_me_endpoint(client, admin_headers):
    me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    assert me["role"] == "admin"


def test_registration_and_weak_password(client):
    weak = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@test.local", "username": "weakuser", "password": "abcdefgh"},
    )
    assert weak.status_code == 422
    assert "digit" in str(weak.json()["detail"])

    bad_email = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "username": "bademail", "password": "GoodPass123"},
    )
    assert bad_email.status_code == 422

    ok = client.post(
        "/api/v1/auth/register",
        json={"email": "user1@test.local", "username": "user1", "password": "GoodPass123"},
    )
    assert ok.status_code == 201
    assert ok.json()["role"] == "editor"  # self-registration cannot pick a role

    duplicate = client.post(
        "/api/v1/auth/register",
        json={"email": "user1@test.local", "username": "other", "password": "GoodPass123"},
    )
    assert duplicate.status_code == 409


def test_token_refresh_and_api_key(client, admin_headers):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "admin@test.local", "password": "TestAdmin123"}
    ).json()
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    # an access token must not be usable as a refresh token
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401

    created = client.post("/api/v1/auth/api-keys", json={"name": "pytest", "expires_in_days": 30}, headers=admin_headers)
    assert created.status_code == 201
    key = created.json()["key"]
    assert client.get("/api/v1/auth/me", headers={"X-API-Key": key}).json()["username"] == "admin"
    assert client.get("/api/v1/auth/me", headers={"X-API-Key": "gf_bogus_key"}).status_code == 401

    revoked = client.delete(f"/api/v1/auth/api-keys/{created.json()['id']}", headers=admin_headers)
    assert revoked.status_code == 204
    assert client.get("/api/v1/auth/me", headers={"X-API-Key": key}).status_code == 401


# --------------------------------------------------------------------------- #
# projects / RBAC
# --------------------------------------------------------------------------- #
def test_project_crud_and_membership(client, admin_headers, project):
    detail = client.get(f"/api/v1/projects/{project['id']}", headers=admin_headers).json()
    assert detail["my_role"] == "owner"
    assert len(detail["members"]) == 1

    patched = client.patch(
        f"/api/v1/projects/{project['id']}", json={"description": "updated"}, headers=admin_headers
    ).json()
    assert patched["description"] == "updated"

    client.post(
        "/api/v1/auth/register",
        json={"email": "viewer@test.local", "username": "viewer", "password": "ViewerPass123"},
    )
    added = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"username": "viewer", "role": "viewer"},
        headers=admin_headers,
    )
    assert added.status_code == 201
    assert added.json()["role"] == "viewer"


def test_viewer_cannot_edit_but_can_read(client, admin_headers, project):
    client.post(
        "/api/v1/auth/register",
        json={"email": "viewer2@test.local", "username": "viewer2", "password": "ViewerPass123"},
    )
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"username": "viewer2", "role": "viewer"},
        headers=admin_headers,
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": "viewer2", "password": "ViewerPass123"}
    ).json()["access_token"]
    viewer = {"Authorization": f"Bearer {token}"}

    seq = client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={"name": "rbac_target", "sequence": "ATGCATGCATGC"},
        headers=admin_headers,
    ).json()

    assert client.get(f"/api/v1/sequences/{seq['id']}", headers=viewer).status_code == 200
    assert (
        client.post(
            f"/api/v1/sequences/{seq['id']}/edit",
            json={"operations": [{"op": "delete", "start": 0, "end": 3}]},
            headers=viewer,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/sequences",
            json={"name": "nope", "sequence": "ATGC"},
            headers=viewer,
        ).status_code
        == 403
    )


def test_non_member_cannot_see_project(client, admin_headers, project):
    client.post(
        "/api/v1/auth/register",
        json={"email": "outsider@test.local", "username": "outsider", "password": "Outsider123"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": "outsider", "password": "Outsider123"}
    ).json()["access_token"]
    outsider = {"Authorization": f"Bearer {token}"}
    assert client.get(f"/api/v1/projects/{project['id']}", headers=outsider).status_code == 403
    listed = client.get("/api/v1/projects", headers=outsider).json()
    assert all(p["id"] != project["id"] for p in listed["items"])


def test_admin_only_endpoints(client, admin_headers):
    client.post(
        "/api/v1/auth/register",
        json={"email": "plain@test.local", "username": "plainuser", "password": "PlainPass123"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": "plainuser", "password": "PlainPass123"}
    ).json()["access_token"]
    plain = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/users", headers=plain).status_code == 403
    assert client.get("/api/v1/audit-logs", headers=plain).status_code == 403
    assert client.get("/api/v1/stats", headers=plain).status_code == 403
    assert client.get("/api/v1/users", headers=admin_headers).status_code == 200


# --------------------------------------------------------------------------- #
# sequences
# --------------------------------------------------------------------------- #
def test_import_genbank_and_export_round_trip(client, admin_headers, project, demo_plasmid_gb):
    res = client.post(
        f"/api/v1/projects/{project['id']}/sequences/import",
        files={"file": ("pGF-EGFP.gb", io.BytesIO(demo_plasmid_gb.encode()), "text/plain")},
        headers=admin_headers,
    )
    assert res.status_code == 201, res.text
    payload = res.json()
    assert payload["detected_format"] == "genbank"
    record = payload["imported"][0]
    assert record["length"] == 2832
    assert record["topology"] == "circular"
    assert record["feature_count"] == 13

    detail = client.get(f"/api/v1/sequences/{record['sequence_id']}", headers=admin_headers).json()
    assert detail["gc_content"] > 40
    assert any(f["name"] == "EGFP" for f in detail["features"])

    exported = client.get(
        f"/api/v1/sequences/{record['sequence_id']}/export?format=genbank&download=false",
        headers=admin_headers,
    )
    assert exported.status_code == 200
    assert exported.text.startswith("LOCUS")
    assert "EGFP" in exported.text

    fasta = client.get(
        f"/api/v1/sequences/{record['sequence_id']}/export?format=fasta&download=false", headers=admin_headers
    ).text
    assert fasta.startswith(">")


def test_import_text_and_stats(client, admin_headers, project):
    res = client.post(
        f"/api/v1/projects/{project['id']}/sequences/import-text",
        json={"content": ">pasted\nATGCATGCATGCGGGCCC", "filename": "pasted.fasta"},
        headers=admin_headers,
    )
    assert res.status_code == 201
    seq_id = res.json()["imported"][0]["sequence_id"]
    stats = client.get(f"/api/v1/sequences/{seq_id}/stats", headers=admin_headers).json()
    assert stats["length"] == 18
    assert stats["gc"] > 50


def test_import_text_requires_payload(client, admin_headers, project):
    res = client.post(
        f"/api/v1/projects/{project['id']}/sequences/import-text", json={}, headers=admin_headers
    )
    assert res.status_code == 422


def test_edit_operations_create_versions_and_can_be_restored(client, admin_headers, project):
    seq = client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={"name": "editable", "sequence": "AAAAGGGGTTTTCCCC", "topology": "circular"},
        headers=admin_headers,
    ).json()
    feature = client.post(
        f"/api/v1/sequences/{seq['id']}/features",
        json={"name": "block", "type": "CDS", "start": 4, "end": 8, "strand": 1},
        headers=admin_headers,
    ).json()
    assert feature["start"] == 4

    # adding a feature is itself a version, so annotation work is undoable
    assert client.get(f"/api/v1/sequences/{seq['id']}", headers=admin_headers).json()["current_version"] == 2

    edited = client.post(
        f"/api/v1/sequences/{seq['id']}/edit",
        json={"operations": [{"op": "insert", "position": 2, "payload": "TT"}], "message": "insert TT"},
        headers=admin_headers,
    ).json()
    assert edited["length"] == 18
    assert edited["current_version"] == 3
    assert edited["features"][0]["start"] == 6

    rotated = client.post(
        f"/api/v1/sequences/{seq['id']}/edit",
        json={"operations": [{"op": "set_origin", "origin": 6}]},
        headers=admin_headers,
    ).json()
    assert rotated["current_version"] == 4
    assert rotated["length"] == 18

    versions = client.get(f"/api/v1/sequences/{seq['id']}/versions", headers=admin_headers).json()
    assert [v["version"] for v in versions] == [4, 3, 2, 1]
    assert versions[-1]["message"] == "Initial version"

    # restoring the feature-only version brings the sequence and the feature back
    restored = client.post(f"/api/v1/sequences/{seq['id']}/versions/2/restore", headers=admin_headers).json()
    assert restored["sequence"] == "AAAAGGGGTTTTCCCC"
    assert restored["current_version"] == 5
    assert restored["features"][0]["start"] == 4

    # and version 1 is the pristine, feature-free import
    pristine = client.post(f"/api/v1/sequences/{seq['id']}/versions/1/restore", headers=admin_headers).json()
    assert pristine["features"] == []


def test_set_origin_requires_circular(client, admin_headers, project):
    seq = client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={"name": "linear_only", "sequence": "ATGCATGCATGC"},
        headers=admin_headers,
    ).json()
    res = client.post(
        f"/api/v1/sequences/{seq['id']}/edit",
        json={"operations": [{"op": "set_origin", "origin": 3}]},
        headers=admin_headers,
    )
    assert res.status_code == 422
    assert "circular" in res.json()["message"]


def test_feature_crud_and_clipping(client, admin_headers, project):
    seq = client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={"name": "featured", "sequence": "ATGC" * 25},
        headers=admin_headers,
    ).json()
    created = client.post(
        f"/api/v1/sequences/{seq['id']}/features",
        json={"name": "f1", "type": "promoter", "start": 10, "end": 30, "strand": -1},
        headers=admin_headers,
    ).json()
    updated = client.patch(
        f"/api/v1/sequences/{seq['id']}/features/{created['id']}",
        json={"name": "renamed", "end": 40},
        headers=admin_headers,
    ).json()
    assert updated["name"] == "renamed"
    assert updated["end"] == 40
    assert updated["segments"] == [[10, 40]]

    too_long = client.post(
        f"/api/v1/sequences/{seq['id']}/features",
        json={"name": "bad", "type": "CDS", "start": 0, "end": 5000},
        headers=admin_headers,
    )
    assert too_long.status_code == 422

    assert (
        client.delete(f"/api/v1/sequences/{seq['id']}/features/{created['id']}", headers=admin_headers).status_code
        == 204
    )
    assert client.get(f"/api/v1/sequences/{seq['id']}/features", headers=admin_headers).json() == []


def test_auto_annotate_and_copy(client, admin_headers, project):
    seq = client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={
            "name": "annotate_me",
            "sequence": "TAATACGACTCACTATAG" + "GGAATTGTGAGCGGATAACAATT" + "A" * 200,
        },
        headers=admin_headers,
    ).json()
    annotated = client.post(
        f"/api/v1/sequences/{seq['id']}/auto-annotate?replace=true", headers=admin_headers
    ).json()
    names = {f["name"] for f in annotated["features"]}
    assert "T7 promoter" in names

    copied = client.post(f"/api/v1/sequences/{seq['id']}/copy?new_name=clone", headers=admin_headers).json()
    assert copied["name"] == "clone"
    assert copied["sequence"] == annotated["sequence"]
    assert copied["id"] != seq["id"]


def test_sequence_deletion(client, admin_headers, project):
    seq = client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={"name": "delete_me", "sequence": "ATGCATGC"},
        headers=admin_headers,
    ).json()
    assert client.delete(f"/api/v1/sequences/{seq['id']}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/v1/sequences/{seq['id']}", headers=admin_headers).status_code == 404


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #
def test_enzyme_catalogue_and_search(client, admin_headers, project):
    catalogue = client.get("/api/v1/tools/enzymes?common_only=true", headers=admin_headers).json()
    assert catalogue["count"] > 20
    assert all(e["common"] for e in catalogue["enzymes"])

    seq = client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={"name": "mcs", "sequence": "AAGCTTGCATGCCTGCAGGTCGACTCTAGAGGATCCCCGGGTACCGAGCTCGAATTC"},
        headers=admin_headers,
    ).json()
    scan = client.post(
        "/api/v1/tools/enzymes/search",
        json={"sequence_id": seq["id"], "common_only": True, "unique_only": True},
        headers=admin_headers,
    ).json()
    enzymes = {row["enzyme"] for row in scan["summary"]}
    assert {"EcoRI", "BamHI", "HindIII"} <= enzymes
    assert all(row["unique"] for row in scan["summary"])


def test_digest_endpoint_returns_gel(client, admin_headers, project):
    seq = client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={"name": "digest_me", "sequence": "GAATTC" + "A" * 300 + "GGATCC" + "T" * 200, "topology": "circular"},
        headers=admin_headers,
    ).json()
    result = client.post(
        "/api/v1/tools/digest",
        json={"sequence_id": seq["id"], "enzymes": ["EcoRI", "BamHI"]},
        headers=admin_headers,
    ).json()
    assert sum(result["fragment_sizes"]) == 512
    assert len(result["gel"]["lanes"]) == 2
    assert result["ligation"] is not None


def test_translate_and_orf_endpoints(client, admin_headers):
    res = client.post(
        "/api/v1/tools/translate",
        json={"sequence": "ATGGTGAGCAAGGGCGAGGAGCTGTTCACC", "frame": 0},
        headers=admin_headers,
    ).json()
    assert res["protein"] == "MVSKGEELFT"
    assert res["molecular_weight"] > 0

    six = client.post(
        "/api/v1/tools/translate", json={"sequence": "ATGGCGATTACC", "six_frame": True}, headers=admin_headers
    ).json()
    assert len(six["frames"]) == 6

    orfs = client.post(
        "/api/v1/tools/orf",
        json={"sequence": "TTT" + "ATG" + "GCT" * 60 + "TAA", "min_aa": 20},
        headers=admin_headers,
    ).json()
    assert orfs["count"] >= 1
    assert orfs["orfs"][0]["aa_length"] == 61  # Met + 60 Ala


def test_primer_design_and_pcr_endpoints(client, admin_headers, project, rng_template):
    seq = client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={"name": "primer_template", "sequence": rng_template},
        headers=admin_headers,
    ).json()
    design = client.post(
        "/api/v1/tools/primers/design",
        json={"sequence_id": seq["id"], "target_start": 300, "target_end": 800, "max_pairs": 2},
        headers=admin_headers,
    ).json()
    assert design["count"] >= 1
    pair = design["pairs"][0]

    pcr = client.post(
        "/api/v1/tools/pcr",
        json={
            "sequence_id": seq["id"],
            "forward": pair["forward"]["sequence"],
            "reverse": pair["reverse"]["sequence"],
        },
        headers=admin_headers,
    ).json()
    assert pcr["specific"]
    assert pcr["products"][0]["size"] == pair["product_size"]

    analysis = client.post(
        "/api/v1/tools/primers/analyze", json={"sequence": pair["forward"]["sequence"]}, headers=admin_headers
    ).json()
    assert analysis["tm"] == pair["forward"]["tm"]


def test_primer_design_validates_target(client, admin_headers):
    res = client.post(
        "/api/v1/tools/primers/design",
        json={"sequence": "ATGCATGCATGCATGCATGC", "target_start": 10, "target_end": 5},
        headers=admin_headers,
    )
    assert res.status_code == 422


def test_alignment_endpoints(client, admin_headers, rng_template):
    res = client.post(
        "/api/v1/tools/align",
        json={"query": rng_template[300:500], "target": rng_template, "mode": "glocal"},
        headers=admin_headers,
    ).json()
    assert res["identity"] == 100.0
    assert res["target_start"] == 300

    msa = client.post(
        "/api/v1/tools/align/multiple",
        json={
            "sequences": [
                {"name": "a", "sequence": rng_template[:200]},
                {"name": "b", "sequence": rng_template[:200].replace("A", "T", 1)},
            ]
        },
        headers=admin_headers,
    ).json()
    assert msa["width"] >= 200
    assert len(msa["rows"]) == 2


def test_alignment_requires_two_inputs(client, admin_headers):
    assert client.post("/api/v1/tools/align", json={"query": "ATGC"}, headers=admin_headers).status_code == 422
    assert (
        client.post("/api/v1/tools/align/multiple", json={"sequences": []}, headers=admin_headers).status_code == 422
    )


def test_annotate_endpoint_can_persist(client, admin_headers, project):
    seq = client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={"name": "apply_annotations", "sequence": "TAATACGACTCACTATAG" + "C" * 150},
        headers=admin_headers,
    ).json()
    res = client.post(
        "/api/v1/tools/annotate",
        json={"sequence_id": seq["id"], "apply": True, "include_orfs": False},
        headers=admin_headers,
    ).json()
    assert res["count"] >= 1
    assert res["applied"] == res["count"]
    detail = client.get(f"/api/v1/sequences/{seq['id']}", headers=admin_headers).json()
    assert len(detail["features"]) == res["count"]


def test_annotation_transfer(client, admin_headers, project, demo_plasmid_gb):
    imported = client.post(
        f"/api/v1/projects/{project['id']}/sequences/import",
        files={"file": ("ref.gb", io.BytesIO(demo_plasmid_gb.encode()), "text/plain")},
        headers=admin_headers,
    ).json()["imported"][0]
    reference = client.get(f"/api/v1/sequences/{imported['sequence_id']}", headers=admin_headers).json()

    mutated = reference["sequence"][:1000] + "A" + reference["sequence"][1001:]
    target = client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={"name": "unannotated_clone", "sequence": mutated, "topology": "circular"},
        headers=admin_headers,
    ).json()

    res = client.post(
        "/api/v1/tools/annotate/transfer",
        json={
            "reference_sequence_id": reference["id"],
            "target_sequence_id": target["id"],
            "apply": True,
        },
        headers=admin_headers,
    ).json()
    assert res["count"] >= 10
    assert res["applied"] is True
    detail = client.get(f"/api/v1/sequences/{target['id']}", headers=admin_headers).json()
    assert any(f["name"] == "EGFP" for f in detail["features"])


def test_cloning_helpers(client, admin_headers):
    overhangs = client.post(
        "/api/v1/tools/cloning/check-overhangs", json={"a": "AATT", "b": "AATT"}, headers=admin_headers
    ).json()
    assert overhangs["compatible"] is True

    suggestions = client.post(
        "/api/v1/tools/cloning/suggest-enzymes",
        json={"sequence": "GAATTC" + "A" * 200 + "GGATCC" + "T" * 100},
        headers=admin_headers,
    ).json()
    assert any({p["enzyme_a"], p["enzyme_b"]} == {"EcoRI", "BamHI"} for p in suggestions["pairs"])


# --------------------------------------------------------------------------- #
# jobs
# --------------------------------------------------------------------------- #
def test_async_job_lifecycle(client, admin_headers, rng_template):
    submitted = client.post(
        "/api/v1/tools/align",
        json={"query": rng_template[100:400], "target": rng_template, "mode": "glocal", "async_job": True},
        headers=admin_headers,
    )
    assert submitted.status_code == 202
    job_id = submitted.json()["job_id"]

    for _ in range(80):
        job = client.get(f"/api/v1/jobs/{job_id}", headers=admin_headers).json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert job["status"] == "succeeded", job
    assert job["result"]["identity"] == 100.0
    assert job["progress"] == 1.0

    listed = client.get("/api/v1/jobs", headers=admin_headers).json()
    assert any(item["id"] == job_id for item in listed["items"])
    assert client.delete(f"/api/v1/jobs/{job_id}", headers=admin_headers).status_code == 204


def test_unknown_job_type_is_rejected(client, admin_headers):
    res = client.post("/api/v1/jobs", json={"type": "not_a_job", "params": {}}, headers=admin_headers)
    assert res.status_code == 422


def test_job_types_endpoint(client, admin_headers):
    types = client.get("/api/v1/jobs/types", headers=admin_headers).json()["types"]
    assert {"align", "digest", "primer_design", "annotate"} <= set(types)


# --------------------------------------------------------------------------- #
# external registry
# --------------------------------------------------------------------------- #
def test_external_registry_and_url_rendering(client, admin_headers):
    resources = client.get("/api/v1/external/resources?enabled_only=false", headers=admin_headers).json()
    ncbi = next(r for r in resources if "Nucleotide" in r["name"])
    rendered = client.post(
        f"/api/v1/external/resources/{ncbi['id']}/url",
        json={"params": {"accession": "NC_000913.3"}},
        headers=admin_headers,
    ).json()
    assert rendered["url"].endswith("NC_000913.3")

    missing = client.post(
        f"/api/v1/external/resources/{ncbi['id']}/url", json={"params": {}}, headers=admin_headers
    )
    assert missing.status_code == 422


def test_external_fetch_disabled_in_tests(client, admin_headers):
    resources = client.get("/api/v1/external/resources?enabled_only=false", headers=admin_headers).json()
    rest = next(r for r in resources if r["allow_proxy"])
    res = client.post(
        f"/api/v1/external/resources/{rest['id']}/fetch",
        json={"params": {"accession": "NC_000913.3", "db": "nuccore", "id": "x"}},
        headers=admin_headers,
    )
    assert res.status_code == 422
    assert "disabled" in res.json()["message"]


def test_link_resource_cannot_be_proxied(client, admin_headers):
    resources = client.get("/api/v1/external/resources?enabled_only=false", headers=admin_headers).json()
    link = next(r for r in resources if not r["allow_proxy"])
    res = client.post(
        f"/api/v1/external/resources/{link['id']}/fetch",
        json={"params": {"accession": "X", "plasmid_id": "1", "sequence": "ATGC", "id": "y"}},
        headers=admin_headers,
    )
    assert res.status_code == 422


# --------------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------------- #
def test_audit_trail_records_mutations(client, admin_headers, project):
    client.post(
        f"/api/v1/projects/{project['id']}/sequences",
        json={"name": "audited", "sequence": "ATGCATGC"},
        headers=admin_headers,
    )
    logs = client.get("/api/v1/audit-logs?size=300", headers=admin_headers).json()
    actions = {entry["action"] for entry in logs["items"]}
    assert "sequence.create" in actions
    assert "project.create" in actions
    assert "user.login" in actions
    assert "feature.create" in actions
