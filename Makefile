# Makefile for the Jarvis project (see CLAUDE.md for full context).
#
# Prerequisite: the sibling Infra repo's stack (Postgres, infra-net, shared
# NGINX) must already be up before `make up` here. See CLAUDE.md.

-include .env
export

.DEFAULT_GOAL := help

.PHONY: help up down restart build rebuild ps logs logs-api logs-frontend logs-batch logs-ingest \
        health health-batch migrate test test-backend test-batch test-ingest test-shared \
        install-frontend dev-frontend build-frontend lint-frontend clean info

help: ## Show this help
	@echo "Jarvis — available targets:"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

up: ## Build (if needed) and start api + frontend + batch + ingest in the background
	@echo "🚀 Starting environment..."
	docker compose up -d --build

down: ## Stop and remove the api + frontend + batch + ingest containers
	@echo "🛑 Stopping environment..."
	docker compose down

restart: down up ## Restart the environment (down, then up)

build: ## Build the api + frontend + batch + ingest images without starting them
	docker compose build

rebuild: ## Rebuild images from scratch, ignoring the layer cache
	docker compose build --no-cache

ps: ## Show status of this project's containers (ingest is normally "Exited")
	docker compose ps

logs: ## Stream logs for all services (SERVICE=api|frontend|batch|ingest to filter)
	docker compose logs -f $(SERVICE)

logs-api: ## Stream logs for the api service only
	docker compose logs -f api

logs-frontend: ## Stream logs for the frontend service only
	docker compose logs -f frontend

logs-batch: ## Stream logs for the batch service only
	docker compose logs -f batch

logs-ingest: ## Stream logs for the ingest service's last run
	docker compose logs -f ingest

health: ## Curl the backend health endpoint
	@curl -sf http://localhost:$${API_PORT:-8000}/health | head -c 500 || \
		(echo "\n❌ backend not reachable on port $${API_PORT:-8000}"; exit 1)

health-batch: ## Curl the batch worker's internal health endpoint via docker exec
	@docker compose exec batch wget -qO- http://localhost:8080/health || \
		(echo "\n❌ batch health endpoint not reachable"; exit 1)

migrate: ## Run Alembic migrations (needs DATABASE_URL reachable + pgvector prerequisite, see CLAUDE.md)
	cd shared && pip install -q -e . && DATABASE_URL=$${DATABASE_URL:-postgres://jarvis:$${JARVIS_DB_PASSWORD}@127.0.0.1:5432/jarvis} python -m alembic upgrade head

test: test-shared test-backend test-batch test-ingest ## Alias for test-shared + test-backend + test-batch + test-ingest

test-shared: ## Run the shared package's pytest suite (no live services needed)
	cd shared && pip install -q -r requirements-dev.txt && pytest

test-backend: ## Run backend pytest suite (no live services needed — settings/db/minio are mocked)
	cd backend && pip install -q -r requirements-dev.txt && pytest

test-batch: ## Run batch pytest suite (settings/db/minio/docker are mocked, no live services needed)
	cd batch && pip install -q -r requirements-dev.txt && pytest

test-ingest: ## Run ingest pytest suite (settings/db/minio/LM Studio are mocked, no live services needed)
	cd ingest && pip install -q -r requirements-dev.txt && pytest

install-frontend: ## npm install the frontend deps
	cd frontend && npm install

dev-frontend: install-frontend ## Run the frontend Vite dev server on :5173 (undockerized)
	cd frontend && npm run dev

build-frontend: install-frontend ## Type-check and production-build the frontend
	cd frontend && npm run build

lint-frontend: install-frontend ## Lint the frontend
	cd frontend && npm run lint

clean: down ## Stop the environment and remove dangling images/build cache for this project
	docker image prune -f --filter label=com.docker.compose.project=$$(basename $$(pwd))

info: ## Show project metadata
	@echo "📊 Project Metadata:"
	@echo "Version: 1.0.0"
	@echo "Status: 🏗️ In Progress"
