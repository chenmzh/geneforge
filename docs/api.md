# API guide

Interactive reference: **`/docs`** (Swagger UI) · **`/redoc`** · schema `/openapi.json`.
Base path: `/api/v1`. All payloads are JSON unless noted.

Coordinates in the API are **0-based, half-open** (`start` inclusive, `end` exclusive) —
the same convention as Python slices. The UI and GenBank exports show 1-based positions.

## Authentication

| Method | Use |
| --- | --- |
| `Authorization: Bearer <access_token>` | Interactive clients. 12 h default, refreshable. |
| `X-API-Key: gf_<prefix>_<secret>` | Pipelines, LIMS, cron. Optional expiry, revocable. |

```http
POST /auth/login            {"username": "...", "password": "..."}   -> tokens
POST /auth/refresh          {"refresh_token": "..."}                 -> tokens
GET  /auth/me                                                        -> current user
POST /auth/change-password  {"current_password": "...", "new_password": "..."}
GET  /auth/api-keys | POST /auth/api-keys | DELETE /auth/api-keys/{id}
POST /auth/register         (only when ALLOW_REGISTRATION=true; always role=editor)
```

## Roles

Global role (`admin` / `editor` / `viewer`) plus per-project role
(`owner` / `editor` / `viewer`); the effective permission is the stricter of the two.

| Action | viewer | editor | owner | admin |
| --- | --- | --- | --- | --- |
| read project & sequences | ✅ | ✅ | ✅ | ✅ |
| create/edit sequences, features, primers | ❌ | ✅ | ✅ | ✅ |
| manage members, rename/delete project | ❌ | ❌ | ✅ | ✅ |
| users, audit log, instance stats, resource registry | ❌ | ❌ | ❌ | ✅ |

## System

```http
GET /health          liveness
GET /ready           readiness (checks the database)
GET /capabilities    formats, limits, queue backend, enzyme count
GET /me/summary      dashboard counters + recent constructs
GET /stats           instance statistics (admin)
GET /audit-logs      audit trail, filterable by action/entity/user (admin)
```

## Projects

```http
GET    /projects?search=&include_archived=&page=&size=
POST   /projects                     {"name","description","tags":[]}
GET    /projects/{id}                includes members + your role
PATCH  /projects/{id}                owner only
DELETE /projects/{id}                owner only, cascades to sequences
GET    /projects/{id}/members
POST   /projects/{id}/members        {"username"|"email", "role"}
DELETE /projects/{id}/members/{user_id}
```

## Sequences

```http
GET    /projects/{id}/sequences?search=&page=&size=
POST   /projects/{id}/sequences      {"name","sequence","topology","features":[],"auto_annotate":false}
GET    /sequences/{id}               full record incl. features
PATCH  /sequences/{id}               metadata only (name, description, topology, annotations)
DELETE /sequences/{id}
POST   /sequences/{id}/copy?new_name=&target_project_id=
GET    /sequences/{id}/stats         composition, ORF count, GC track, MW, Tm
GET    /sequences/{id}/export?format=genbank|fasta|plain&download=true
```

### Import

```http
POST /projects/{id}/sequences/import           multipart file=@construct.gb
     ?format=&auto_annotate=&name_prefix=
POST /projects/{id}/sequences/import-text      {"content": "..."} or {"url": "https://..."}
```

Formats are sniffed (FASTA, GenBank, EMBL, FASTQ, SnapGene `.dna`, plain). The response
lists what was imported and what was skipped, and the detected format:

```json
{"imported":[{"sequence_id":"…","name":"pGF-EGFP","length":2832,"topology":"circular",
              "feature_count":13,"source_format":"genbank"}],
 "skipped":[],"detected_format":"genbank","file_id":"…"}
```

### Editing (versioned)

```http
POST /sequences/{id}/edit
{"operations":[{"op":"insert","position":100,"payload":"GAATTC"}],"message":"add EcoRI"}
```

| `op` | Fields | Effect |
| --- | --- | --- |
| `insert` | `position`, `payload` | Features after the point shift; a feature spanning it grows |
| `delete` | `start`, `end` | Features inside are dropped, overlapping ones truncated |
| `replace` | `start`, `end`, `payload` | Delete + insert in one version |
| `reverse_complement` | – | Whole sequence; strands flip, coordinates mirror |
| `reverse_complement_range` | `start`, `end` | Region only; fully contained features flip |
| `set_origin` | `origin` | Circular only; features crossing the new junction split into segments |
| `set_topology` | `topology` | `linear` ↔ `circular` |

Operations are applied in order and produce **one** new version.

### Versions

```http
GET  /sequences/{id}/versions                 newest first
GET  /sequences/{id}/versions/{n}             sequence + feature snapshot
POST /sequences/{id}/versions/{n}/restore     appends a new version (history is immutable)
```

### Features

```http
GET    /sequences/{id}/features
POST   /sequences/{id}/features   {"name","type","start","end","strand","color","qualifiers"}
PATCH  /sequences/{id}/features/{feature_id}
DELETE /sequences/{id}/features/{feature_id}
POST   /sequences/{id}/auto-annotate?replace=false&min_orf_aa=80
```

## Tools

Reference data:

```http
GET /tools/enzymes?common_only=&search=&overhang=&type_iis=
GET /tools/codon-tables · /tools/feature-library · /tools/ladders
```

Every analysis accepts either `sequence` (inline) **or** `sequence_id` (stored, access
checked). Heavy requests return `202` with `{"job_id": ...}` instead of a result.

```http
POST /tools/composition          base counts, GC track, MW, Tm
POST /tools/translate            frame | six_frame, table_id 1/2/11
POST /tools/orf                  min_aa, both_strands, require_start
POST /tools/enzymes/search       sites + per-enzyme summary + cloning suggestions
POST /tools/digest               fragments, overhangs, virtual gel, ligation matrix
POST /tools/digest/gel           gel from arbitrary sizes
POST /tools/primers/analyze      Tm, GC, ΔG, hairpin, dimer, warnings
POST /tools/primers/design       scored pairs, optional restriction tails
POST /tools/primers/sequencing   tiled sequencing primers
POST /tools/primers/gibson       homology-arm primers
POST /tools/pcr                  products, binding sites, mismatches, Ta
POST /tools/align                global | local | glocal, auto reverse-complement
POST /tools/align/multiple       center-star MSA + consensus + identity matrix
POST /tools/annotate             detect elements/ORFs, optionally persist (apply=true)
POST /tools/annotate/transfer    map a reference's features onto another construct
POST /tools/cloning/suggest-enzymes · /tools/cloning/check-overhangs
```

Example — design and verify in two calls:

```json
POST /tools/primers/design
{"sequence_id": "…", "target_start": 551, "target_end": 1271, "opt_tm": 60, "max_pairs": 3}

POST /tools/pcr
{"sequence_id": "…", "forward": "AATTCGCCACCATGATGG", "reverse": "CACCTTACTTGTACAGCTCG"}
→ {"products":[{"start":537,"end":1275,"size":738,…}],"specific":true,"annealing_temp":56.9}
```

## Jobs

```http
GET  /jobs/types                   registered handlers
POST /jobs                         {"type":"align","params":{…},"project_id":"…"}
GET  /jobs?status=&type=&project_id=
GET  /jobs/{id}                    status, progress (0..1), result, error
POST /jobs/{id}/cancel             pending jobs only
DELETE /jobs/{id}
```

Poll pattern used by the UI: submit → poll every ~700 ms → read `result` on `succeeded`.

## External databases

```http
GET    /external/resources?enabled_only=
POST   /external/resources            (admin) {"name","kind","url_template","allow_proxy"}
PATCH  /external/resources/{id}       (admin)
DELETE /external/resources/{id}       (admin)
POST   /external/resources/seed       (admin) restore the defaults
POST   /external/resources/{id}/url   render the link without calling it
POST   /external/resources/{id}/fetch server-side fetch, optional import_to_project
GET    /external/proxy-policy         effective allow-list
```

`kind=link` is rendered in the browser; `kind=rest` can be fetched server-side when
`allow_proxy` is true **and** the host is on `EXTERNAL_PROXY_ALLOWLIST`. Templates use
`{placeholders}`, e.g. `https://lims.internal/api/plasmid/{id}?format=genbank`.

## Errors

```json
{"code": "permission_denied", "message": "Requires project role 'editor' or higher"}
```

| Status | `code` | Meaning |
| --- | --- | --- |
| 401 | `unauthenticated` | Missing/expired token or bad API key |
| 403 | `permission_denied` | Authenticated but not allowed |
| 404 | `not_found` | Unknown or inaccessible id |
| 409 | `conflict` | Duplicate email/username, removing an owner |
| 413 | `payload_too_large` | Upload or sequence over the configured limit |
| 422 | `validation_error` | Schema or domain validation failed (`detail` explains) |
| 502 | `external_service_error` | Upstream database/API failed |

Every response carries `X-Request-ID` and `X-Response-Time-ms`; the request id also
appears in the structured server logs.
