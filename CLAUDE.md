# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

The repo is split into one top-level directory per container, orchestrated centrally by the root `docker-compose.yml` and `Makefile` — `backend/`, `frontend/`, `batch/`, and `ingest/` today, plus a non-container `shared/` package they all depend on, with more containers expected over time.

### Shared package (`shared/`)

`shared/jarvis_shared/` is an installable local package (`pip install ./shared` or `-e ../shared` for dev) holding the config/db/storage/model patterns that `backend`, `batch`, and `ingest` all need identically:

- `jarvis_shared/config.py` — `SharedSettings`, a `pydantic-settings` base with the fields every container needs (`DATABASE_URL`, OTEL vars, `MINIO_*`). Each container's own `app/config.py` subclasses this and adds its own app-specific fields (see each section below) rather than importing it directly.
- `jarvis_shared/db.py` — the shared `Base` (`DeclarativeBase`), `make_engine()`/`make_session_factory()` factories, `check_connection()`. `make_engine(..., register_vector_codec=True)` registers pgvector's asyncpg codec on every connection — only `ingest` passes this, since turning it on unconditionally would make every container's DB connection depend on the `vector` Postgres extension existing.
- `jarvis_shared/storage.py` — boto3/MinIO helpers (`get_s3_client`, `put_object`, `get_object`, `delete_object`, `count_objects`, `ensure_bucket`).
- `jarvis_shared/models.py` — all SQLAlchemy ORM models (`Item`, `Task`, `ChatSession`, `ChatMessageRecord`, `Folder`, `StoredFile`, `FileChunk`), bound to the shared `Base`.
- `jarvis_shared/migrations/` — Alembic environment (see "Database" below).

Each container's own `app/config.py`/`db.py`/`models.py` are thin subclasses/re-exports of the above (e.g. `backend/app/models.py` just re-exports the names it needs from `jarvis_shared.models`), so existing `from app.models import X`-style imports in routers/jobs keep working unchanged. `telemetry.py`, `healthserver.py`/`health_state.py`, and each container's own `main.py`/routers/jobs stay per-container — genuinely different behavior, not just shared data shape.

This package exists because `batch`'s config/db/storage were **deliberately duplicated** from `backend/app/` rather than shared, with this repo's own prior note: *"introducing [a shared package] for a second consumer would be premature. Revisit if a third container needs the same pattern."* `ingest` (below) is that third consumer, so the duplication was collapsed into `shared/` at that point instead of copy-pasting a third time.

### Backend (`backend/`)

A FastAPI backend lives in `backend/app/`:

- `backend/app/main.py` — FastAPI app, CORS middleware, Prometheus `/metrics`, router registration, startup lifespan (runs `Base.metadata.create_all` for the pre-Alembic tables — see "Database" below).
- `backend/app/telemetry.py` — OpenTelemetry setup (OTLP/HTTP traces + logging instrumentation); no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is empty.
- `backend/app/config.py` — `Settings(SharedSettings)` adding backend-specific fields (`CORS_ORIGINS`, `LMSTUDIO_BASE_URL`/`LMSTUDIO_MODEL` for chat).
- `backend/app/db.py` — thin wrapper around `jarvis_shared.db`'s factories; still exposes `Base`, `engine`, `get_db()`, `check_connection()` at the same import paths as before.
- `backend/app/models.py` — re-exports the ORM models it needs from `jarvis_shared.models`.
- `backend/app/schemas.py` — Pydantic request/response models.
- `backend/app/routers/` — one `APIRouter` per resource (`health.py`, `items.py`, `tasks.py`, `chat.py`, `files.py`). `files.py` uses `jarvis_shared.storage` for all MinIO calls (no inline boto3 client of its own).
- `backend/tests/` — pytest + `httpx` async test client against the ASGI app directly (no live server needed; settings are monkeypatched to an in-memory SQLite DB, so no live Postgres/MinIO is required either).

### Frontend (`frontend/`)

A React + Vite web portal lives in `frontend/`, currently a single page showing live backend health (polls `GET /health` every ~5s). No routing/state library yet — add them only once the portal grows past a single view.

- `frontend/src/useHealthPoll.ts` — polling hook (interval `fetch`, no external data-fetching library), types the `/health` response shape and distinguishes network errors from 503 responses.
- `frontend/src/HealthStatus.tsx` — renders the polled status.
- `frontend/Dockerfile` — multi-stage build: `npm run build` then serves the static `dist/` via nginx. `VITE_API_URL` is a **build-time** arg (baked into the static bundle) since it's a browser-facing URL — it must point at the backend's published host port (e.g. `http://localhost:8000`), not an internal Docker network name.

The dockerized frontend has no published host port — it's on `infra-net` and reached through the Infra repo's shared NGINX at `jarvis.famillelallier.net` (see `nginx/conf.d/jarvis.conf` there), not `localhost:5173`. `localhost:5173` is only for the undockerized `npm run dev` flow below.

### Batch worker (`batch/`)

A long-running Python worker lives in `batch/app/`, with an internal cron (no system crontab, no external job broker):

- `batch/app/main.py` — entrypoint. Starts telemetry, a stdlib health server, and an `AsyncIOScheduler` (APScheduler) that runs each registered job on its own interval, plus once immediately on startup. Waits on `SIGTERM`/`SIGINT` for graceful shutdown.
- `batch/app/jobs/` — one module per job, registered in `batch/app/jobs/__init__.py`'s `registered_jobs()`:
  - `heartbeat.py` — pings Postgres, counts MinIO objects, logs the result. Skeleton example.
  - `ingest_trigger.py` — checks Postgres for `StoredFile` rows with `ingested_at IS NULL`; if any exist, uses docker-py against `/var/run/docker.sock` to start the (normally stopped) `jarvis-ingest` container, skipping if it's already running. See "Ingestion" below.
- `batch/app/healthserver.py` + `batch/app/health_state.py` — a minimal stdlib `GET /health` endpoint (no FastAPI/uvicorn) reporting whether the last job run succeeded; this is what Docker Compose's `healthcheck:` probes, since "the process is alive" alone doesn't prove the scheduler is actually ticking.
- `batch/app/config.py`, `batch/app/db.py`, `batch/app/storage.py` — thin wrappers around `jarvis_shared` (see "Shared package" above); `batch/app/telemetry.py` stays independently duplicated (OTEL setup differs slightly per container).
- `batch/tests/` — same fake-settings-monkeypatch pattern as `backend/tests/conftest.py`, so `make test-batch` needs no live Postgres/MinIO/Docker daemon.

No HTTP API surface besides `/health` — jobs that need to expose data should write to Postgres or MinIO for `backend`/`frontend` to read, not serve their own routes.

**Security note on `ingest_trigger`:** mounting `/var/run/docker.sock` into `batch` (see `docker-compose.yml`) grants it root-equivalent access to the Docker host — anything with that socket can start/stop/inspect *any* container on the host and create new ones with arbitrary mounts, not just `jarvis-ingest`. This is a materially larger blast radius than anything else in this repo. `batch`'s Dockerfile running as non-root (`appuser`) does **not** mitigate this — Docker daemon socket auth is all-or-nothing regardless of in-container UID. The `:ro` mount is best-effort hardening only (the socket's own API doesn't respect filesystem read-only semantics for its write operations). A `docker-socket-proxy` sidecar scoping this down to just `containers.start`/`get` on `jarvis-ingest` would close this gap but hasn't been built yet — a reasonable follow-up, not yet done.

### Ingestion (`ingest/`)

A normally-stopped, one-shot Python container that does the actual RAG file-ingestion work — chunking and embedding files uploaded through the backend's Files feature (`backend/app/routers/files.py`) so they become retrievable later.

- `ingest/app/main.py` — entrypoint: runs one ingestion pass, exits 0 on full success or 1 if anything failed (so `docker inspect`/`docker compose ps` shows a distinguishable exit code). No HTTP surface, no scheduler of its own — `batch/app/jobs/ingest_trigger.py` starts it.
- `ingest/app/pipeline.py` — orchestration: finds `StoredFile` rows with `ingested_at IS NULL`, skips (but still stamps) unsupported content-types, pulls bytes from MinIO, chunks, embeds, writes `FileChunk` rows, stamps `ingested_at`. Commits per-file so a crash mid-run only leaves the *current* file unprocessed, not ones already done.
- `ingest/app/chunking.py` — naive fixed-size character windows with overlap (`INGEST_CHUNK_SIZE_CHARS`/`INGEST_CHUNK_OVERLAP_CHARS`). No tokenizer, no sentence-awareness — deliberately minimal until retrieval quality can actually be measured.
- `ingest/app/embeddings.py` — calls LM Studio's OpenAI-compatible `/v1/embeddings` endpoint (`EMBEDDING_LMSTUDIO_BASE_URL`/`EMBEDDING_LMSTUDIO_MODEL` — **separate** from backend's `LMSTUDIO_MODEL`, which is a chat model, not an embedding model), batching all of a file's chunks into one request.
- `ingest/app/db.py` — the one container that passes `register_vector_codec=True` to `jarvis_shared.db.make_engine()`, since it's the only one reading/writing `FileChunk.embedding`.
- `ingest/tests/` — chunking is pure-function tested; embeddings mock `httpx`; the pipeline test uses a real in-memory SQLite DB (pgvector's `Vector` type works fine there for basic DDL/insert/select) with MinIO and the embeddings call mocked. No live Postgres/MinIO/LM Studio/Docker needed.

**Text extraction scope:** only plainly-text `content_type`s (`text/*`, `application/json`, `.md`/`.txt` fallback by extension) are actually chunked and embedded. Binary formats (PDF, DOCX, images) are skipped-but-stamped (`ingested_at` still gets set, so `ingest_trigger` doesn't loop forever retrying a file it can never process) — extracting text from those is a deliberately deferred follow-up.

**Power-up mechanics:** `docker-compose.yml`'s `ingest` service has `restart: "no"` and a fixed `container_name: jarvis-ingest`. It runs once per start and exits, so between triggers it just sits "Exited" — there's no polling loop or idle process to manage.

### Database: uses the Infra repo's Postgres

Neither the backend, batch worker, nor ingest container runs its own Postgres. All three connect to the Postgres instance managed in the sibling `Infra` repo (`/Users/nicolaslallier/Claude/Infra`), over an external Docker network called `infra-net`, at hostname `postgres:5432`.

Infra reserves this app as `jarvis`: database `jarvis`, role `jarvis`, password in the `JARVIS_DB_PASSWORD` env var (must match between Infra's `.env` and this repo's `.env`). See Infra's own README/CLAUDE.md for the full provisioning convention (`APP_DATABASES`, `postgres/initdb/10-provision-apps.sh`).

**Prerequisite before running this backend:** the `jarvis` DB/role must exist in Infra's running Postgres cluster.
- Infra stack not started yet: set `JARVIS_DB_PASSWORD` in Infra's `.env`, then `make up` in the Infra repo.
- Infra stack already running: `make provision-app app=jarvis` in the Infra repo.

**Schema management — `create_all` plus Alembic.** The original tables (`items`, `tasks`, `chat_sessions`, `chat_messages`, `folders`, `files`) are still created via `Base.metadata.create_all` in `backend/app/main.py`'s startup lifespan, kept for backwards compatibility. Alembic (`shared/jarvis_shared/migrations/`) was introduced for everything past that baseline, because adding a Postgres **extension** and altering an existing table are both things `create_all` cannot express at all. Run migrations manually with `make migrate` — deliberately not automatic on container boot, since three containers restarting simultaneously and all racing `alembic upgrade head` would be worse than a manual step. A fresh database should be stamped at the baseline revision (`alembic stamp 0001` from `shared/`) before the first real `make migrate`.

**Prerequisite before running ingestion:** the `vector` extension (pgvector) must be available in Infra's Postgres before `make migrate` runs.
- If Infra's Postgres image isn't already pgvector-capable, that's an Infra-repo image swap — this repo can't change what image Infra runs.
- A Postgres superuser must be able to run `CREATE EXTENSION IF NOT EXISTS vector` against the `jarvis` database — the `jarvis` app role likely lacks that privilege, the same reasoning as why db/role provisioning happens via Infra's superuser `initdb` scripts, not this repo. Whether this becomes part of Infra's `postgres/initdb/10-provision-apps.sh` or a one-off manual step is an Infra-repo decision.
- `shared/jarvis_shared/migrations/versions/0002_pgvector_ingestion.py` issues the `CREATE EXTENSION` statement itself as a convenience, but will fail with a clear permissions error if Infra hasn't done its part — that failure is the signal to go make the Infra-repo change first, not a bug in the migration.

## Build / run / test

```bash
# one-time: copy env template and set JARVIS_DB_PASSWORD to match Infra's .env
cp .env.example .env

# build and run all containers (requires Infra's stack + infra-net already up)
docker compose build
docker compose up -d
# ^ ingest builds and runs once on cold start, then sits "Exited" — that's
#   expected (see "Ingestion" above), not a crash.

# one-time (and after any new migration): apply Alembic migrations.
# Needs the pgvector prerequisite in the "Database" section above.
make migrate

# sanity check
curl http://localhost:8000/health
curl http://localhost:8000/docs
open https://jarvis.famillelallier.net   # frontend portal, via Infra's NGINX
docker compose exec batch wget -qO- http://localhost:8080/health

# shared/backend/batch/ingest tests all mock settings/db/minio/docker/LM
# Studio, so none of them need a live Postgres, MinIO, or Docker daemon —
# `make test` runs all four. Individually:
cd shared  && pip install -r requirements-dev.txt && pytest
cd backend && pip install -r requirements-dev.txt && pytest
cd batch   && pip install -r requirements-dev.txt && pytest
cd ingest  && pip install -r requirements-dev.txt && pytest

# frontend local dev (without Docker)
cd frontend
npm install
npm run dev   # http://localhost:5173, calls VITE_API_URL (frontend/.env, defaults to http://localhost:8000)
```

Note: `docker-compose.yml` here can't `depends_on` Infra's `postgres` service (it's a different Compose project) — start Infra's stack first.
