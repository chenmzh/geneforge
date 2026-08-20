# GeneForge — developer entry points. Run `make help` for the list.
SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
VENV := $(BACKEND)/.venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
API_HOST ?= 127.0.0.1
API_PORT ?= 8090

.DEFAULT_GOAL := help
.PHONY: help setup backend-setup frontend-setup dev api web build test test-api lint \
        migrate migration samples smoke ui-check docker-up docker-down docker-logs clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: backend-setup frontend-setup ## Install backend and frontend dependencies

backend-setup: ## Create the venv and install Python dependencies
	python3 -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r $(BACKEND)/requirements-dev.txt
	@test -f $(BACKEND)/.env || cp .env.example $(BACKEND)/.env
	@echo "backend ready — edit $(BACKEND)/.env before production use"

frontend-setup: ## Install frontend dependencies
	cd $(FRONTEND) && pnpm install

api: ## Run the API (SQLite + in-process queue) on $(API_HOST):$(API_PORT)
	cd $(BACKEND) && .venv/bin/python -m uvicorn app.main:app --reload --host $(API_HOST) --port $(API_PORT)

web: ## Run the Vite dev server (proxies /api to the API)
	cd $(FRONTEND) && pnpm run dev

dev: ## Reminder of the two dev processes
	@echo "run 'make api' in one terminal and 'make web' in another (http://localhost:5173)"

build: ## Build the SPA into backend/app/static
	cd $(FRONTEND) && ./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build

test: ## Run the backend test suite
	cd $(BACKEND) && .venv/bin/python -m pytest

test-cov: ## Run tests with coverage for the bio engine
	cd $(BACKEND) && .venv/bin/python -m pytest --cov=app/bio --cov-report=term-missing

lint: ## Ruff (backend) + tsc (frontend)
	cd $(BACKEND) && .venv/bin/python -m ruff check app scripts tests
	cd $(FRONTEND) && ./node_modules/.bin/tsc --noEmit

migrate: ## Apply database migrations
	cd $(BACKEND) && .venv/bin/python -m alembic upgrade head

migration: ## Autogenerate a migration: make migration m="add table"
	cd $(BACKEND) && .venv/bin/python -m alembic revision --autogenerate -m "$(m)"

samples: ## Regenerate the demo sequences in samples/
	cd $(BACKEND) && .venv/bin/python -m scripts.make_samples

smoke: ## End-to-end API smoke test against a running server
	cd $(BACKEND) && bash scripts/smoke.sh http://$(API_HOST):$(API_PORT)

docker-up: ## Build and start the full stack (Postgres, Redis, API, worker, nginx)
	docker compose up -d --build
	@echo "GeneForge on http://localhost:$${HTTP_PORT:-8080}"

docker-down: ## Stop the stack
	docker compose down

docker-logs: ## Tail stack logs
	docker compose logs -f --tail=100

clean: ## Remove build artefacts, caches and the dev database
	rm -rf $(BACKEND)/app/static/assets $(BACKEND)/app/static/index.html
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/geneforge.db*
	find $(BACKEND) -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf $(FRONTEND)/dist $(FRONTEND)/node_modules/.vite
