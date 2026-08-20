# Architecture

## 1. Layering

```
                        ┌─────────────────────────────────────────┐
  HTTP / JWT / API key  │  app/api/v1/*  routers                  │  thin: validate,
                        │  app/api/deps.py  auth + RBAC           │  authorise, delegate
                        └───────────────┬─────────────────────────┘
                                        │
                        ┌───────────────▼─────────────────────────┐
                        │  app/services/*                          │  transactions,
                        │  projects · sequences · users · external │  permissions,
                        │  audit · bootstrap                       │  audit
                        └───────────────┬─────────────────────────┘
                          ┌─────────────┴───────────────┐
        ┌─────────────────▼──────────┐   ┌──────────────▼─────────────────┐
        │  app/models + app/db       │   │  app/bio/*                     │
        │  SQLAlchemy, Alembic       │   │  pure functions, no DB, no HTTP │
        └────────────────────────────┘   └────────────────────────────────┘
                                                        ▲
                        ┌───────────────────────────────┴─────────┐
                        │  app/tasks/*  queue + handlers          │
                        │  same handlers run inline or on Celery  │
                        └─────────────────────────────────────────┘
```

Rules that keep the layers honest:

1. **`app/bio` never imports FastAPI, SQLAlchemy or settings.** It takes strings and
   dataclasses and returns dataclasses. That is why it can be unit-tested at speed and
   reused from a notebook, a Celery worker or a CLI.
2. **Routers never touch the ORM for permission decisions.** `services/projects.py`
   owns `require_access(db, project, user, minimum)`; every route funnels through it
   (usually via the `ProjectAccess` dependency), so there is one place to audit.
3. **Task handlers take `(db, params, progress)`** and nothing else. The same function
   is called by `run_sync()` during a request and by `run_job()` inside a worker.
4. **Every mutation writes an audit row** through `services/audit.record()` in the same
   transaction as the change, so the trail cannot drift from the data.

## 2. Data model

```
users ──┬── api_keys
        ├── project_members ──┐
        └── audit_logs        │
                             projects ──┬── sequences ──┬── features
                                        │              └── sequence_versions
                                        ├── primers
                                        ├── imported_files
                                        └── jobs
external_resources (global registry)
```

Design notes:

* **String UUID primary keys** (`String(36)`) keep the schema identical on SQLite and
  PostgreSQL and make IDs safe to expose in URLs.
* **`sequences.sequence` is `Text`.** A 5 Mb ceiling (`MAX_SEQUENCE_LENGTH`) is enforced
  in the service layer; anything larger belongs in a genome browser, not a plasmid editor.
* **Features are relational *and* snapshotted.** Live features are rows (queryable,
  individually editable); each version stores a JSON snapshot so a restore is a single
  read. Coordinates are **0-based half-open**, exactly like Python slices, and are
  converted to 1-based only at the GenBank/UI boundary — this eliminates the classic
  off-by-one class of bugs.
* **`segments` is a JSON list of `[start, end]` pairs** so joined CDSs and features that
  span a circular origin are first-class, not a special case.
* **Versions are immutable.** Sequence edits always create one; feature-only edits create
  one too when `VERSION_FEATURE_EDITS=true` (default), because curating annotations is
  the activity users most want to undo. A restore appends a new version rather than
  rewriting history.

## 3. The bio engine

| Module | Responsibility | Notable decisions |
| --- | --- | --- |
| `alphabet` | complement, IUPAC expansion, GC, MW, GC track | one `str.maketrans` table, case preserving |
| `translate` | codon tables 1/2/11, six frames, pI, MW | table built from the classic 64-char string |
| `seqio` | FASTA, GenBank, EMBL, FASTQ, SnapGene `.dna` | permissive readers, strict writer; GenBank writing is idempotent (verified by test) |
| `enzymes` | 162 enzymes, site search | REBASE offsets from the site start; both strands; circular wrap by scanning `seq + seq[:len(site)-1]` |
| `digest` | fragments, gel, ligation, pair suggestions | fragment sizes always sum to the construct length |
| `primers` | Tm, QC, design, PCR | SantaLucia 1998 NN + Owczarzy 2004/2008 salt correction; one shared default buffer so design/QC/simulation agree |
| `align` | affine DP + anchored + MSA | exact DP under `MAX_DP_CELLS`, k-mer anchor+chain above it; auto reverse-complement |
| `annotate` | ORFs, auto-annotation, transfer | element library is JSON data, not code |
| `edit` | insert/delete/replace/revcomp/set-origin | every operation returns `(sequence, features, description)`; features are remapped, split or dropped explicitly |

### Why alignment has two engines

Exact affine-gap DP is O(n·m) in time *and* memory. A 5 kb read against a 50 kb construct
is 250 M cells — unacceptable in a request. So:

* below `MAX_DP_CELLS` (6 M, and `ALIGN_MAX_CELLS_SYNC` for the API gate) → exact DP with
  full traceback, CIGAR and variant calls;
* above it → k-mer seeding (k≈14), diagonal grouping, collinear chaining, per-block
  identity. No traceback, but coordinates, identity and blocks are enough for
  "does my read match, and where", and annotation transfer can still map features through
  the block offsets.

The API routes anything expensive to the job queue, so the UI never blocks either way.

## 4. Request lifecycle

```
request
  → middleware: request id, timing, security headers
  → dependency: get_current_user (JWT or X-API-Key)
  → dependency: ProjectAccess(minimum_role) → (project, user, role)
  → router: validate payload (Pydantic)
  → service: mutate + audit inside one transaction
  → bio engine: pure computation
  → response: Pydantic model (documented in OpenAPI)
```

Errors are normalised: `GeneForgeError` subclasses carry `status_code` + `code`, so every
failure is `{"code": "...", "message": "...", "detail": ...}`. The frontend's `ApiError`
maps onto exactly that shape.

## 5. Task queue

`app/tasks/queue.py` exposes one API to the routers:

```python
submit(db, job_type=..., params=..., user=..., project=...)  # -> Job row
run_sync(db, job_type, params)                               # -> dict, inline
```

* `CELERY_BROKER_URL` set → `execute_job.delay(job.id)`; workers run
  `celery -A app.tasks.celery_app:celery_app worker`.
* Not set → a module-level `ThreadPoolExecutor` runs `run_job(job.id)`.
* If Celery dispatch raises (broker down), the job is downgraded to local execution
  instead of being lost.

Either way the `jobs` row is the contract: the UI polls `GET /jobs/{id}` and shows
`progress` updated by the handler's `progress()` callback.

## 6. Frontend

* **Rendering.** `SequenceViewer` computes the monospace advance width once
  (hidden 100-char probe), derives bases-per-row from the container width, and draws
  absolutely positioned rows so it can virtualise: only the visible ±2 rows exist in the
  DOM. Feature chips and enzyme marks are positioned as `offset × charWidth`, which is
  why they align to the base grid exactly (asserted in a headless-browser geometry check).
* **Plasmid map.** Pure SVG. Features are packed onto concentric rings by overlap; arcs
  are drawn as paths with a strand arrowhead; the ring radius shrinks as enzyme labels
  get longer so labels never leave the viewport.
* **State.** Server state lives in TanStack Query (cache + invalidation after mutations);
  only auth/session and toasts use Zustand. Selection, view mode and panel state are
  component state — they should not survive navigation.
* **Types.** `src/api/types.ts` mirrors the Pydantic schemas by hand. This is deliberate:
  a generated client would be larger and would hide the small number of places where the
  UI intentionally accepts `job_id` *or* a result payload.

## 7. Security posture

* Passwords: PBKDF2-HMAC-SHA256, 240 k iterations, per-password salt, constant-time compare.
* Tokens: short-lived access + longer refresh, `type` claim checked so a refresh token
  cannot be used as an access token.
* API keys: only the SHA-256 digest is stored; the plaintext is shown once.
* Authorisation: global role *and* project role; the stricter of the two wins.
* SSRF: outbound fetches must match `EXTERNAL_PROXY_ALLOWLIST`, be `http(s)`, and resolve
  to a public address; redirects are not followed and responses are size-capped.
* Uploads: size-capped, sniffed rather than trusted by extension, and plain text must be
  ≥90 % nucleotides before it is accepted as a sequence.
* Audit: who did what, to which entity, from which IP, with a JSON detail blob.

## 8. Known limits

* Multiple alignment is center-star, not progressive/iterative — fine for a handful of
  related constructs, not for a phylogeny.
* The anchored aligner reports blocks, not a base-level alignment.
* Auto-annotation is signature based: it finds what is in the library, nothing more.
* The virtual gel is a log-size approximation, not a mobility model.
* Feature-only versions store the full sequence text; disable `VERSION_FEATURE_EDITS`
  for genome-scale records.
