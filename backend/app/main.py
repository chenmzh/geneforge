"""FastAPI application factory: middleware, error handling, OpenAPI, static SPA."""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.v1 import api_router
from .core.config import settings
from .core.exceptions import GeneForgeError
from .core.logging import configure_logging, get_logger

logger = get_logger("geneforge.app")

DESCRIPTION = """
**GeneForge** is a modular platform for DNA/plasmid visualisation, editing and analysis.

* **Projects & sequences** — versioned constructs with feature annotations and RBAC
* **Import/Export** — FASTA, GenBank, EMBL, FASTQ and SnapGene `.dna`
* **Analysis** — restriction mapping, virtual digests and gels, primer design & QC,
  PCR simulation, pairwise/multiple alignment, ORF finding, auto-annotation
* **Jobs** — long-running analyses run on Celery (or an in-process pool for single-node installs)
* **External registry** — configurable deep links and allow-listed server-side fetches (NCBI, Ensembl, UniProt...)

Authenticate with `POST /api/v1/auth/login` and send `Authorization: Bearer <access_token>`,
or use a long-lived `X-API-Key` header for pipelines.
""".strip()

TAGS_METADATA = [
    {"name": "system", "description": "Health, readiness and capability discovery."},
    {"name": "auth", "description": "Login, token refresh, API keys."},
    {"name": "users", "description": "User administration and the audit trail."},
    {"name": "projects", "description": "Projects and membership (RBAC)."},
    {"name": "sequences", "description": "Sequence CRUD, editing, versions, features, import/export."},
    {"name": "tools", "description": "Molecular biology analysis endpoints."},
    {"name": "jobs", "description": "Background job submission and polling."},
    {"name": "external", "description": "External database/API registry and proxy."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    from .db.session import create_all
    from .services.bootstrap import bootstrap

    if settings.is_sqlite or settings.environment != "production":
        create_all()
    bootstrap()
    logger.info(
        "%s %s started (env=%s, queue=%s, db=%s)",
        settings.app_name,
        settings.app_version,
        settings.environment,
        "celery" if settings.queue_enabled else "local",
        "sqlite" if settings.is_sqlite else "postgres",
    )
    yield
    from .tasks.queue import shutdown

    shutdown()


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        root_path=settings.root_path,
        lifespan=lifespan,
        contact={"name": "GeneForge", "url": "https://example.org/geneforge"},
        license_info={"name": "MIT"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-Request-ID"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except GeneForgeError as exc:  # raised outside route handlers
            response = JSONResponse(status_code=exc.status_code, content=exc.to_payload())
        duration = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = f"{duration:.1f}"
        if request.url.path.startswith(settings.api_prefix):
            logger.info(
                "%s %s -> %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "method": request.method,
                    "status_code": response.status_code,
                    "duration_ms": round(duration, 1),
                    "user_id": getattr(request.state, "user_id", None),
                },
            )
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.exception_handler(GeneForgeError)
    async def geneforge_error_handler(_: Request, exc: GeneForgeError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Request validation failed",
                # pydantic can put exception objects in ctx; encode defensively
                "detail": jsonable_encoder(exc.errors(), custom_encoder={Exception: str}),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": "http_error", "message": str(exc.detail)},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception(
            "unhandled error on %s %s", request.method, request.url.path,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        payload = {"code": "internal_error", "message": "Internal server error"}
        if settings.debug:
            payload["detail"] = f"{type(exc).__name__}: {exc}"
        return JSONResponse(status_code=500, content=payload)

    app.include_router(api_router, prefix=settings.api_prefix)

    # --- static SPA (built frontend) ------------------------------------- #
    dist = settings.frontend_dist
    if settings.serve_frontend and dist.exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        async def spa_root():
            index = dist / "index.html"
            if index.exists():
                return FileResponse(index)
            return JSONResponse({"message": f"{settings.app_name} API", "docs": "/docs"})

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_catchall(full_path: str):
            candidate = dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            index = dist / "index.html"
            if index.exists():
                return FileResponse(index)
            return JSONResponse({"code": "not_found", "message": "Not found"}, status_code=404)
    else:

        @app.get("/", include_in_schema=False)
        async def api_root():
            return {
                "app": settings.app_name,
                "version": settings.app_version,
                "docs": "/docs",
                "openapi": "/openapi.json",
                "api": settings.api_prefix,
                "frontend": "not built — run 'pnpm build' in frontend/ or use the Vite dev server",
            }

    return app


app = create_app()
