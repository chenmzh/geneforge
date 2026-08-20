# GeneForge

[![CI](https://github.com/chenmzh/geneforge/actions/workflows/ci.yml/badge.svg)](https://github.com/chenmzh/geneforge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![React 18](https://img.shields.io/badge/react-18-149eca)

A SnapGene-style **DNA / plasmid workbench** you can host yourself: visualise and edit
constructs, curate annotations, map restriction sites, run virtual digests and gels,
design and QC primers, simulate PCR, align sequencing reads — all behind project-level
access control, an audit trail, a task queue and a documented REST API.

```
┌──────────── browser ────────────┐
│  React SPA (linear + circular   │
│  viewers, editor, tool panels)  │
└───────────────┬─────────────────┘
                │ REST + JWT / API key
┌───────────────▼─────────────────┐      ┌───────────────┐
│  FastAPI (api + static SPA)     │◄────►│  PostgreSQL   │
│  services · RBAC · audit        │      └───────────────┘
│  ┌───────────────────────────┐  │      ┌───────────────┐
│  │ bio engine (pure Python)  │  │◄────►│ Redis + Celery│
│  └───────────────────────────┘  │      └───────────────┘
└─────────────────────────────────┘
```

---

## 1. Quick start

```bash
git clone git@github.com:chenmzh/geneforge.git    # or: gh repo clone chenmzh/geneforge
cd geneforge
```

### Option A — laptop, no Docker (SQLite + in-process queue)

```bash
make setup            # venv + python deps, pnpm install, backend/.env from template
make build            # compile the SPA into backend/app/static
make api              # http://127.0.0.1:8090  (docs at /docs)
```

Open <http://127.0.0.1:8090> and sign in with the bootstrap administrator
(`admin@geneforge.local` / `ChangeMe123!` — change it immediately). On first start the
server creates the schema, seeds the external-resource registry and imports the demo
plasmid from `samples/`.

For frontend development run the API and the Vite dev server side by side:

```bash
make api              # terminal 1
make web              # terminal 2 -> http://localhost:5173 (proxies /api)
```

### Option B — full stack with Docker

```bash
cp .env.example .env                     # then edit SECRET_KEY, passwords
python -c "import secrets; print(secrets.token_urlsafe(48))"   # SECRET_KEY
make docker-up                           # http://localhost:8080
```

That brings up PostgreSQL, Redis, the API, a Celery worker and nginx. Migrations run
automatically on container start.

### Verify an installation

```bash
make test             # 87 backend tests (bio engine, I/O, API, RBAC, jobs)
make smoke            # end-to-end API walk-through against a running server
make lint             # ruff + tsc
```

The same checks run in CI (`.github/workflows/ci.yml`) on every push, plus two extra
gates: Alembic must round-trip (`upgrade → downgrade → upgrade`) with **no schema drift**
against the models, and the Docker image is built and smoke-tested (health, SPA, login,
digest) before the run is considered green.

---

## 2. Feature tour

| Area | What you get |
| --- | --- |
| **Visualisation** | Wrapped linear viewer (ruler, both strands, 3-frame translation, feature lanes, enzyme cut marks, drag selection, row virtualisation for 100 kb+) and a circular plasmid map (feature arcs with strand arrowheads, concentric lanes, GC ring, enzyme labels, click-to-seek) |
| **Editing** | Insert / delete / replace / reverse-complement (whole or selection) / set origin / linear↔circular, with **feature coordinate remapping** and an immutable version per change |
| **Annotation** | Manual features with GenBank qualifiers and colours, data-driven auto-annotation (33 built-in elements: promoters, tags, resistance markers, recombination sites…), ORF finding, and annotation **transfer from a reference by alignment** |
| **Restriction analysis** | 162-enzyme catalogue (REBASE-style offsets, Type IIS aware), site search on both strands with circular wrap-around, single/double/multi digests, fragment overhangs, ligation compatibility, enzyme-pair suggestions for directional cloning |
| **Virtual gel** | Log-size migration model, four ladders, agarose-percentage aware |
| **Primers** | Nearest-neighbour Tm (SantaLucia 1998 + Owczarzy 2004/2008 salt correction), GC clamp, hairpin/self-dimer/cross-dimer heuristics, 3′ end stability, primer-pair design with scoring, restriction/Gibson tails, sequencing-primer tiling, PCR simulation (mismatch tolerant, origin-spanning products) |
| **Alignment** | Affine-gap DP (global / local / glocal) with automatic reverse-complement detection, k-mer anchored fallback for long inputs, variant calling (substitutions / insertions / deletions), center-star multiple alignment with consensus |
| **Import / export** | FASTA, GenBank, EMBL, FASTQ, **SnapGene `.dna`** (binary), plain text, URL fetch; export GenBank / FASTA / raw. GenBank round-trips are idempotent |
| **Projects & security** | Projects with owner/editor/viewer membership, global admin/editor/viewer roles, JWT access+refresh, API keys for pipelines, full audit trail, SSRF-guarded external fetching |
| **Jobs** | Celery when a broker is configured, in-process thread pool otherwise — same `jobs` table and API either way |

---

## 3. Technology choices

| Layer | Choice | Why |
| --- | --- | --- |
| API | **FastAPI** + Pydantic v2 | Async-capable, generates the OpenAPI docs the brief requires, validation is declarative |
| ORM | **SQLAlchemy 2.0 (sync)** | Typed models; sync sessions keep transactions obvious and FastAPI runs them in a threadpool |
| DB | **PostgreSQL** (SQLite for dev/test) | JSON columns for qualifiers/params, real constraints; SQLite keeps the dev loop and CI dependency-free |
| Migrations | **Alembic** | Autogenerate verified against the models (`make migrate`) |
| Queue | **Celery + Redis**, with a thread-pool fallback | Long alignments must not block requests; small installs should not need a broker |
| Auth | **JWT (PyJWT)** + PBKDF2-SHA256 + API keys | No native build dependencies; API keys suit LIMS/pipeline access |
| Bio engine | **hand-written, pure standard library** | No Biopython/primer3 build chain, deterministic behaviour, exact control over circular topology and coordinate remapping — and it is unit-tested against known values (EGFP translation, REBASE cut sites, IDT/NEB Tm) |
| Frontend | **React 18 + TypeScript + Vite** | Strict typing against the API schema, instant HMR, small bundle (≈96 kB gzipped) |
| State | **Zustand** + **TanStack Query** | Local UI state stays trivial; server state gets caching/refetching for free |
| Rendering | **plain SVG + DOM** | Sequence and map rendering is bespoke; no charting library can draw a plasmid map, and hand-rolled SVG keeps it accessible and printable |

**Deliberate non-choices:** no Biopython (heavy, and we need circular-aware editing anyway),
no ORM-level multi-tenancy magic (project membership is checked in one service function),
no WebSockets (job polling is enough and survives proxies).

---

## 4. Repository layout

```
14_dna_editor/
├── backend/
│   ├── app/
│   │   ├── bio/                 # dependency-free science core
│   │   │   ├── alphabet.py      # complement, IUPAC, GC, MW, GC track
│   │   │   ├── translate.py     # codon tables, six frames, protein properties
│   │   │   ├── seqio.py         # FASTA/GenBank/EMBL/FASTQ/SnapGene .dna I/O
│   │   │   ├── enzymes.py       # 162-enzyme catalogue + site search
│   │   │   ├── digest.py        # digests, fragments, gel, ligation
│   │   │   ├── primers.py       # thermodynamics, design, PCR simulation
│   │   │   ├── align.py         # affine DP + anchored + center-star MSA
│   │   │   ├── annotate.py      # ORFs, auto-annotation, transfer
│   │   │   ├── edit.py          # edit ops with feature remapping
│   │   │   └── feature_library.json   # extensible auto-annotation library
│   │   ├── api/v1/              # routers: auth, users, projects, sequences,
│   │   │                        #          tools, jobs, external, system
│   │   ├── core/                # config, security, exceptions, logging
│   │   ├── db/                  # engine, session, declarative base
│   │   ├── models/              # ORM models (users…audit_logs)
│   │   ├── schemas/             # Pydantic request/response models
│   │   ├── services/            # projects, sequences, users, external, audit, bootstrap
│   │   ├── tasks/               # queue abstraction, handlers, celery app
│   │   ├── static/              # built SPA (generated)
│   │   └── main.py              # app factory, middleware, error handling
│   ├── alembic/                 # migrations (initial schema included)
│   ├── scripts/                 # make_samples.py, smoke.sh
│   ├── tests/                   # 87 tests: bio, seqio, api/RBAC/jobs
│   └── requirements*.txt
├── frontend/
│   └── src/
│       ├── api/                 # typed client + API types
│       ├── components/          # SequenceViewer, PlasmidMap, GelView, Ui, Layout
│       │   └── panels/          # Feature, Enzyme, Primer, Align, Analysis panels
│       ├── pages/               # Login, Dashboard, Projects, ProjectView,
│       │                        # SequenceWorkbench, Jobs, ToolBench, Enzymes,
│       │                        # External, Admin
│       ├── lib/                 # client-side sequence helpers
│       ├── store/               # auth + toast stores
│       └── styles/app.css       # design system
├── deploy/nginx/nginx.conf
├── docs/                        # architecture, api, roadmap, security
├── samples/                     # generated demo constructs
├── docker-compose.yml · Dockerfile · Makefile · .env.example
```

---

## 5. API in 30 seconds

Full interactive reference: **`/docs`** (Swagger UI), **`/redoc`**, schema at `/openapi.json`.
68 documented paths / 85 operations. See `docs/api.md` for a guided tour.

```bash
BASE=http://127.0.0.1:8090/api/v1

# 1. authenticate
TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin@geneforge.local","password":"ChangeMe123!"}' | jq -r .access_token)
AUTH="Authorization: Bearer $TOKEN"

# 2. project + import a GenBank file
PROJ=$(curl -s -X POST $BASE/projects -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Cloning"}' | jq -r .id)
SEQ=$(curl -s -X POST $BASE/projects/$PROJ/sequences/import -H "$AUTH" \
  -F file=@samples/pGF-EGFP.gb | jq -r '.imported[0].sequence_id')

# 3. unique cutters, a digest, and a primer pair
curl -s -X POST $BASE/tools/enzymes/search -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"sequence_id\":\"$SEQ\",\"unique_only\":true}" | jq '.summary[].enzyme'
curl -s -X POST $BASE/tools/digest -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"sequence_id\":\"$SEQ\",\"enzymes\":[\"EcoRI\",\"BamHI\"]}" | jq .fragment_sizes
curl -s -X POST $BASE/tools/primers/design -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"sequence_id\":\"$SEQ\",\"target_start\":551,\"target_end\":1271}" | jq '.pairs[0].product_size'

# 4. edit (versioned) and export
curl -s -X POST $BASE/sequences/$SEQ/edit -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"operations":[{"op":"insert","position":100,"payload":"GAATTC"}],"message":"add EcoRI"}' | jq .current_version
curl -s "$BASE/sequences/$SEQ/export?format=genbank&download=false" -H "$AUTH" | head -3
```

Pipelines can swap the bearer token for a long-lived key: `-H "X-API-Key: gf_…"`.

---

## 6. Configuration

Every setting is an environment variable (see `.env.example` for the annotated list).
The ones that matter most:

| Variable | Default | Notes |
| --- | --- | --- |
| `SECRET_KEY` | random per boot | **Set it** in production or tokens die on restart |
| `DATABASE_URL` | `sqlite:///./geneforge.db` | `postgresql+psycopg://user:pass@host/db` in production |
| `CELERY_BROKER_URL` | empty | Empty = in-process thread pool; set it to use Celery workers |
| `ALLOW_REGISTRATION` | `true` | Set `false` for closed instances (admins create users) |
| `MAX_SEQUENCE_LENGTH` | `5000000` | Rejects oversized records early |
| `ALIGN_MAX_CELLS_SYNC` | `4000000` | Above this an alignment is queued instead of run inline |
| `VERSION_FEATURE_EDITS` | `true` | Snapshot a version when only features change (undoable curation) |
| `EXTERNAL_PROXY_ALLOWLIST` | NCBI/Ensembl/UniProt/EBI | Only these hosts may be fetched server-side |

---

## 7. Extending it

* **New analysis** → add a pure function in `app/bio/`, register a handler in
  `app/tasks/handlers.py`, expose it in `app/api/v1/tools.py`. It is then available
  synchronously *and* as a queued job, with no extra work.
* **New enzymes** → one line in `app/bio/enzymes.py` (`name: (site, fwd_cut, rev_cut, suppliers)`).
* **New auto-annotation elements** → append to `app/bio/feature_library.json`, or pass
  `extra_library` in a `/tools/annotate` request; no code change, no redeploy.
* **New external database** → register it in the UI (*External databases → Register*) or
  `POST /external/resources` with a URL template such as
  `https://lims.internal/api/plasmid/{id}?format=genbank`.
* **New file format** → add a parser to `app/bio/seqio.py` and a branch in `detect_format`.

`docs/architecture.md` explains the module boundaries and the reasoning behind them;
`docs/roadmap.md` lists what the next iterations should add (Gibson/Golden-Gate assembly
simulation, AB1 chromatogram traces, CRISPR guide scoring, real BLAST integration).

---

## 8. Status

* 87 backend tests pass (`make test`); ruff and `tsc --noEmit` are clean.
* The UI was verified in headless Chrome end to end: login → project → workbench →
  digest/gel → primer design → analysis → admin, with **zero console errors** and
  geometry assertions confirming the viewer's base grid, ruler, feature chips and map
  labels align to the pixel.
* The bio engine is validated against known references: the EGFP CDS translates to the
  canonical 239-aa protein, REBASE cut notation matches for palindromic/blunt/Type IIS
  enzymes, digest fragments sum to the construct length (linear and circular), and Tm
  matches IDT/NEB within ~1 °C at 50 mM Na⁺.

MIT licensed. Not a medical device; verify every construct before ordering DNA.
