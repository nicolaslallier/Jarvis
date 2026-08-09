# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

The repo is split into one top-level directory per container, orchestrated centrally by the root `docker-compose.yml` and `Makefile` — `backend/`, `frontend/`, and `batch/` today, with more containers expected over time.

### Backend (`backend/`)

A FastAPI backend lives in `backend/app/`:

- `backend/app/main.py` — FastAPI app, CORS middleware, Prometheus `/metrics`, router registration, startup lifespan (runs `Base.metadata.create_all`).
- `backend/app/telemetry.py` — OpenTelemetry setup (OTLP/HTTP traces + logging instrumentation); no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is empty.
- `backend/app/config.py` — `pydantic-settings`-based settings (`DATABASE_URL`, `CORS_ORIGINS`, `APP_ENV`, OTEL vars), read from `.env`. Normalizes the `postgres://` scheme to `postgresql+asyncpg://` for SQLAlchemy.
- `backend/app/db.py` — async SQLAlchemy engine/session setup, `get_db()` dependency, `check_connection()` health helper.
- `backend/app/models.py` — SQLAlchemy ORM models (currently a minimal `Item` example).
- `backend/app/schemas.py` — Pydantic request/response models.
- `backend/app/routers/` — one `APIRouter` per resource (`health.py`, `items.py`).
- `backend/tests/` — pytest + `httpx` async test client against the ASGI app directly (no live server needed).

No migrations tool yet — schema is created via `create_all` on startup. Add Alembic once the schema needs to evolve past this example.

### Frontend (`frontend/`)

A React + Vite web portal lives in `frontend/`, currently a single page showing live backend health (polls `GET /health` every ~5s). No routing/state library yet — add them only once the portal grows past a single view.

- `frontend/src/useHealthPoll.ts` — polling hook (interval `fetch`, no external data-fetching library), types the `/health` response shape and distinguishes network errors from 503 responses.
- `frontend/src/HealthStatus.tsx` — renders the polled status.
- `frontend/Dockerfile` — multi-stage build: `npm run build` then serves the static `dist/` via nginx. `VITE_API_URL` is a **build-time** arg (baked into the static bundle) since it's a browser-facing URL — it must point at the backend's published host port (e.g. `http://localhost:8000`), not an internal Docker network name.

The dockerized frontend has no published host port — it's on `infra-net` and reached through the Infra repo's shared NGINX at `jarvis.famillelallier.net` (see `nginx/conf.d/jarvis.conf` there), not `localhost:5173`. `localhost:5173` is only for the undockerized `npm run dev` flow below.

### Batch worker (`batch/`)

A long-running Python worker lives in `batch/app/`, with an internal cron (no system crontab, no external job broker):

- `batch/app/main.py` — entrypoint. Starts telemetry, a stdlib health server, and an `AsyncIOScheduler` (APScheduler) that runs each registered job on its own interval, plus once immediately on startup. Waits on `SIGTERM`/`SIGINT` for graceful shutdown.
- `batch/app/jobs/` — one module per job, registered in `batch/app/jobs/__init__.py`'s `registered_jobs()`. Currently just `heartbeat.py` (pings Postgres, counts MinIO objects, logs the result) as a skeleton example — replace/extend with real jobs here.
- `batch/app/healthserver.py` + `batch/app/health_state.py` — a minimal stdlib `GET /health` endpoint (no FastAPI/uvicorn) reporting whether the last job run succeeded; this is what Docker Compose's `healthcheck:` probes, since "the process is alive" alone doesn't prove the scheduler is actually ticking.
- `batch/app/config.py`, `batch/app/db.py`, `batch/app/storage.py`, `batch/app/telemetry.py` — **deliberately duplicated**, not shared, from the equivalent `backend/app/` modules (same pydantic-settings/async-SQLAlchemy/boto3-MinIO patterns). There's no shared/importable package between containers in this repo yet; introducing one for a second consumer would be premature. Revisit if a third container needs the same pattern.
- `batch/tests/` — same fake-settings-monkeypatch pattern as `backend/tests/conftest.py`, so `make test-batch` needs no live Postgres/MinIO.

No HTTP API surface besides `/health` — jobs that need to expose data should write to Postgres or MinIO for `backend`/`frontend` to read, not serve their own routes.

### Database: uses the Infra repo's Postgres

Neither the backend nor the batch worker runs its own Postgres. Both connect to the Postgres instance managed in the sibling `Infra` repo (`/Users/nicolaslallier/Claude/Infra`), over an external Docker network called `infra-net`, at hostname `postgres:5432`.

Infra reserves this app as `jarvis`: database `jarvis`, role `jarvis`, password in the `JARVIS_DB_PASSWORD` env var (must match between Infra's `.env` and this repo's `.env`). See Infra's own README/CLAUDE.md for the full provisioning convention (`APP_DATABASES`, `postgres/initdb/10-provision-apps.sh`).

**Prerequisite before running this backend:** the `jarvis` DB/role must exist in Infra's running Postgres cluster.
- Infra stack not started yet: set `JARVIS_DB_PASSWORD` in Infra's `.env`, then `make up` in the Infra repo.
- Infra stack already running: `make provision-app app=jarvis` in the Infra repo.

## Build / run / test

```bash
# one-time: copy env template and set JARVIS_DB_PASSWORD to match Infra's .env
cp .env.example .env

# build and run all containers (requires Infra's stack + infra-net already up)
docker compose build
docker compose up -d

# sanity check
curl http://localhost:8000/health
curl http://localhost:8000/docs
open https://jarvis.famillelallier.net   # frontend portal, via Infra's NGINX
docker compose exec batch wget -qO- http://localhost:8080/health

# backend tests (in-process ASGI client — no need to build this project's
# Docker image, but DATABASE_URL must point at a reachable Postgres, e.g.
# Infra's nginx passthrough at 127.0.0.1:5432)
cd backend
pip install -r requirements-dev.txt
pytest

# batch tests (settings/db/minio are mocked — no live services needed)
cd batch
pip install -r requirements-dev.txt
pytest

# frontend local dev (without Docker)
cd frontend
npm install
npm run dev   # http://localhost:5173, calls VITE_API_URL (frontend/.env, defaults to http://localhost:8000)
```

Note: `docker-compose.yml` here can't `depends_on` Infra's `postgres` service (it's a different Compose project) — start Infra's stack first.
