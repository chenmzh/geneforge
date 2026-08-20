# Development notes

## Environment
* Python 3.11+ (3.12 tested), Node 20+ (22 tested), pnpm 9+ (11 tested), Docker optional.
* `make setup` creates `backend/.venv`, installs dependencies and copies `.env.example`
  to `backend/.env`.

## Everyday commands
| Command | Purpose |
| --- | --- |
| `make api` | API with autoreload on 127.0.0.1:8090 (SQLite, in-process queue) |
| `make web` | Vite dev server on :5173, proxying `/api` to the API |
| `make build` | Type-check and bundle the SPA into `backend/app/static` |
| `make test` / `make test-cov` | pytest / pytest with bio-engine coverage |
| `make lint` | ruff + `tsc --noEmit` |
| `make migrate` / `make migration m="msg"` | apply / autogenerate migrations |
| `make samples` | regenerate `samples/` demo constructs |
| `make smoke` | end-to-end API walk-through against a running server |

## pnpm notes
pnpm 10+ blocks dependency install scripts and re-verifies the lockfile before `pnpm run`.
`frontend/pnpm-workspace.yaml` and `frontend/.npmrc` approve esbuild's script and skip the
pre-run gate. If `pnpm run build` still refuses in your environment, call the binaries
directly (this is what `make build` does):

```bash
cd frontend && ./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build
```

## Conventions
* Coordinates are 0-based half-open everywhere except GenBank output and UI labels.
* `app/bio` must stay free of FastAPI/SQLAlchemy imports — that boundary is what keeps it
  testable and reusable in workers.
* Permission checks belong in `services/projects.require_access`, never inline in routers.
* Every mutating route writes an audit row in the same transaction.
* New analyses: pure function in `app/bio` → handler in `app/tasks/handlers.py` → route in
  `app/api/v1/tools.py`. You get the sync path and the queued path from one implementation.

## Adding a test
`tests/test_bio.py` covers the science (no DB), `tests/test_seqio.py` the parsers/writers,
`tests/test_api.py` the HTTP surface including RBAC and jobs. The `client`, `admin_headers`,
`project`, `rng_template` and `demo_plasmid_gb` fixtures live in `tests/conftest.py`;
`rng_template` is a deterministic non-repetitive sequence — use it for primer and
alignment tests, because a repetitive template legitimately produces many binding sites.

## Debugging tips
* `GET /api/v1/capabilities` tells you which queue backend and limits are active.
* Jobs keep their traceback in `result.traceback` when `DEBUG=true`.
* Every response carries `X-Request-ID`; grep the JSON logs for it.
* `DB_ECHO=true` logs SQL.
