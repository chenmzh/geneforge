# --- stage 1: build the SPA -------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend

# Install dependencies first so the layer caches on lockfile changes only.
# pnpm 10+ exits non-zero when a dependency's build script is not pre-approved
# (esbuild ships one), even though the install itself succeeded — so verify the
# toolchain is present instead of trusting the exit code, and fail loudly if not.
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc ./
RUN corepack enable \
 && (pnpm install --frozen-lockfile || pnpm install || true) \
 && test -x node_modules/.bin/vite \
 && test -x node_modules/.bin/tsc

COPY frontend/ ./
# call the binaries directly: `pnpm run` re-runs the dependency gate
RUN ./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build

# --- stage 2: python runtime -------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# curl is used by the container healthcheck; no compilers needed (pure-python deps)
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY samples/ ./samples/

# the SPA is served by FastAPI from app/static
COPY --from=frontend /app/backend/app/static ./backend/app/static

RUN useradd --create-home --uid 10001 geneforge \
 && mkdir -p /app/backend/storage \
 && chown -R geneforge:geneforge /app
USER geneforge

WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/v1/health" || exit 1

CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
