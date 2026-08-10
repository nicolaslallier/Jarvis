# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

The repo is split into one top-level directory per container, orchestrated centrally by the root `docker-compose.yml` and `Makefile` — `backend/`, `frontend/`, `batch/`, and `ingest/` today, plus a non-container `shared/` package they all depend on, with more containers expected over time.

### Shared package (`shared/`)

`shared/jarvis_shared/` is an installable local package (`pip install ./shared` or `-e ../shared` for dev) holding the config/db/storage/model patterns that `backend`, `batch`, and `ingest` all need identically:

- `jarvis_shared/config.py` — `SharedSettings`, a `pydantic-settings` base with the fields every container needs (`DATABASE_URL`, OTEL vars, `MINIO_*`, `RABBITMQ_URL`). Each container's own `app/config.py` subclasses this and adds its own app-specific fields (see each section below) rather than importing it directly.
- `jarvis_shared/db.py` — the shared `Base` (`DeclarativeBase`), `make_engine()`/`make_session_factory()` factories, `check_connection()`. `make_engine(..., register_vector_codec=True)` registers pgvector's asyncpg codec on every connection — only `ingest` passes this, since turning it on unconditionally would make every container's DB connection depend on the `vector` Postgres extension existing.
- `jarvis_shared/storage.py` — boto3/MinIO helpers (`get_s3_client`, `put_object`, `get_object`, `delete_object`, `count_objects`, `ensure_bucket`).
- `jarvis_shared/queue.py` — `aio-pika` helpers (`publish_message`, `consume`) plus the `jarvis.ingest.requested`/`jarvis.ingest.completed` queue name constants, used by `backend` and `batch` for the on-demand ingest trigger (see "Ingestion" below).
- `jarvis_shared/models.py` — all SQLAlchemy ORM models (`Item`, `Task`, `ChatSession`, `ChatMessageRecord`, `Folder`, `StoredFile`, `FileChunk`, `Memory`), bound to the shared `Base`.
- `jarvis_shared/migrations/` — Alembic environment (see "Database" below).

Each container's own `app/config.py`/`db.py`/`models.py` are thin subclasses/re-exports of the above (e.g. `backend/app/models.py` just re-exports the names it needs from `jarvis_shared.models`), so existing `from app.models import X`-style imports in routers/jobs keep working unchanged. `telemetry.py`, `healthserver.py`/`health_state.py`, and each container's own `main.py`/routers/jobs stay per-container — genuinely different behavior, not just shared data shape.

This package exists because `batch`'s config/db/storage were **deliberately duplicated** from `backend/app/` rather than shared, with this repo's own prior note: *"introducing [a shared package] for a second consumer would be premature. Revisit if a third container needs the same pattern."* `ingest` (below) is that third consumer, so the duplication was collapsed into `shared/` at that point instead of copy-pasting a third time.

### Backend (`backend/`)

A FastAPI backend lives in `backend/app/`:

- `backend/app/main.py` — FastAPI app, CORS middleware, Prometheus `/metrics`, router registration, startup lifespan (runs `Base.metadata.create_all` for the pre-Alembic tables — see "Database" below — and starts a background task consuming `jarvis.ingest.completed` off RabbitMQ, relaying each message to `ws_manager.broadcast`).
- `backend/app/telemetry.py` — OpenTelemetry setup (OTLP/HTTP traces + logging instrumentation); no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is empty.
- `backend/app/config.py` — `Settings(SharedSettings)` adding backend-specific fields (`CORS_ORIGINS`, `LMSTUDIO_BASE_URL`/`LMSTUDIO_MODEL` for chat, `EMBEDDING_LMSTUDIO_BASE_URL`/`EMBEDDING_LMSTUDIO_MODEL`/`RAG_TOP_K` for the RAG retrieval below, `MEMORY_TOP_K` for the memory retrieval below, `SEARCH_CHUNK_TOP_K`/`SEARCH_MEMORY_TOP_K` for the global search feature below — deliberately separate knobs from `RAG_TOP_K`/`MEMORY_TOP_K` since a search results page wants more hits than a chat context injection does).
- `backend/app/db.py` — thin wrapper around `jarvis_shared.db`'s factories; still exposes `Base`, `engine`, `get_db()`, `check_connection()` at the same import paths as before. Deliberately does **not** pass `register_vector_codec=True` (see `jarvis_shared/db.py`'s docstring) — `backend/app/rag.py` and `backend/app/memory.py` below read/write their pgvector columns via raw-SQL `CAST(... AS vector)` instead, precisely so the backend's every-request DB connection doesn't hard-depend on the `vector` extension existing.
- `backend/app/models.py` — re-exports the ORM models it needs from `jarvis_shared.models`.
- `backend/app/schemas.py` — Pydantic request/response models.
- `backend/app/vector_format.py` — `format_vector_literal()`, the pgvector text-format helper (`"[0.1,0.2,0.3]"`) shared by `rag.py` and `memory.py` so both can pass embeddings as a plain string parameter cast to `vector` in SQL.
- `backend/app/embeddings.py` — `embed_text()`, the single LM Studio `/v1/embeddings` call (`EMBEDDING_LMSTUDIO_BASE_URL`/`EMBEDDING_LMSTUDIO_MODEL`) every embedding consumer in this container shares: `chat.py` (embedding the incoming user message once for both RAG and memory retrieval below), `routers/memory.py`'s `POST /memories` journal-note endpoint, and `search_service.py` below. Returns `None` (never raises) on any failure — network error, non-200, malformed body — so best-effort callers can just treat `None` as "no embedding available" instead of catching exceptions themselves.
- `backend/app/rag.py` — RAG retrieval for chat: `fetch_relevant_chunks()` runs a raw-SQL cosine-distance (`<=>`) nearest-neighbor query against `file_chunks`, `format_context()` renders the results as a system-message block. Uses the same `EMBEDDING_LMSTUDIO_BASE_URL`/`EMBEDDING_LMSTUDIO_MODEL` model `ingest` used to embed the chunks (see "Ingestion" below) — a query embedded with a different model isn't comparable to them.
- `backend/app/memory.py` — cross-session memory, the counterpart to `rag.py` but for facts learned about the user in conversation rather than uploaded documents: `fetch_relevant_memories()`/`format_memory_context()` mirror `rag.py`'s retrieval against a `memories` table instead of `file_chunks`; `parse_extracted_facts()` leniently pulls a JSON array of facts out of the extraction model's (possibly prose- or code-fence-wrapped) reply; `store_memories()` inserts new facts with their embeddings via the same raw-SQL `CAST(... AS vector)` pattern (writing, not just reading, since the ORM `Vector` type would need the codec this container deliberately doesn't register). Has no LM Studio/httpx calls of its own — `chat.py` below (via `app/embeddings.py`) owns the outbound embedding call and passes the results in, same separation as `rag.py`.
- `backend/app/search_service.py` — global search across tasks, appointments, chat messages, file_chunks, and memories (backs `GET /search`, see `routers/search.py` below). `search(db, embed_fn, query, limits)` runs five lookups and returns one flat, unranked list: `Task.title`/`Task.description` and `Appointment.title`/`Appointment.description` and `ChatMessageRecord.content` via plain `ILIKE` (always run, no embedding needed), plus `file_chunks` and `memories` via the exact `CAST(:query_vector AS vector)` cosine-distance pattern `rag.py`/`memory.py` use (only run if `embed_fn` — normally `app/embeddings.py`'s `embed_text`, injected via the `search_with_defaults()` wrapper — produces an embedding; a failure there just skips those two legs, same best-effort discipline as chat's retrievals). `score` is `None` for the `ILIKE` kinds and the raw cosine distance for the vector kinds — deliberately never unified into one cross-kind relevance number.
- `backend/app/ws_manager.py` — a small `ConnectionManager` tracking active WebSocket clients and broadcasting JSON payloads to all of them; used by the ingest-completion relay above.
- `backend/app/routers/` — one `APIRouter` per resource (`health.py`, `items.py`, `tasks.py`, `chat.py`, `files.py`, `ingest_status.py`, `search.py`). `chat.py` always leads the model call with `SECRETARY_SYSTEM_PROMPT`, a fixed persona system message establishing the assistant as the user's personal secretary (day/week/life management, tasks, follow-ups). `send_message` embeds the user's message once (via `app/embeddings.py`'s `embed_text`) and reuses that embedding for two retrievals: `app/rag.py`'s `fetch_relevant_chunks()` (top `RAG_TOP_K` `file_chunks`) and `app/memory.py`'s `fetch_relevant_memories()` (top `MEMORY_TOP_K` `memories`), injecting whichever succeed as leading system messages after the persona prompt (not persisted as `ChatMessageRecord`s, so neither is repeated back into history on the next turn). Both retrievals are best-effort: any failure (LM Studio unreachable, `vector` extension/table not provisioned yet, nothing found) is caught and logged, falling back to a plain chat call — they're a quality boost, never a reason a message fails to send. After the reply is generated and persisted, `chat.py` also calls `app/memory.py`'s extraction path: it asks the chat model to pull any durable facts out of the exchange (via `memory.py`'s `EXTRACTION_SYSTEM_PROMPT`), embeds them, and stores them with `store_memories()` — same best-effort handling, so a broken extraction call never undoes an otherwise-successful send. `files.py` uses `jarvis_shared.storage` for all MinIO calls (no inline boto3 client of its own) and exposes `POST /files/{id}/ingest`, which publishes a `jarvis.ingest.requested` message instead of touching Docker directly. `ingest_status.py` exposes the `GET /ws/ingest-status` WebSocket the frontend listens on. `search.py` exposes `GET /search?q=...` (see `app/search_service.py` above), resolving `SEARCH_CHUNK_TOP_K`/`SEARCH_MEMORY_TOP_K` from `Settings` into a `SearchLimits`.
- `backend/tests/` — pytest + `httpx` async test client against the ASGI app directly (no live server needed; settings are monkeypatched to an in-memory SQLite DB, and the RabbitMQ consumer is monkeypatched to a no-op, so no live Postgres/MinIO/RabbitMQ is required either).

### Frontend (`frontend/`)

A React + Vite web portal lives in `frontend/`, currently a single page showing live backend health (polls `GET /health` every ~5s). No routing/state library yet — add them only once the portal grows past a single view.

- `frontend/src/useHealthPoll.ts` — polling hook (interval `fetch`, no external data-fetching library), types the `/health` response shape and distinguishes network errors from 503 responses.
- `frontend/src/HealthStatus.tsx` — renders the polled status.
- `frontend/src/useFiles.ts` — besides folder/file CRUD, opens a WebSocket to `GET /ws/ingest-status` (reconnects on close) and re-runs `load()` on every message, so ingest completion updates the file list without polling. `requestIngest(id)` calls `POST /files/{id}/ingest`; `FilesPage.tsx` renders an "Ingérer" button per pending file (disabled while queued, per `queuedFileIds`, until the next WS-triggered reload clears it).
- `frontend/src/useSearch.ts` + `frontend/src/SearchPage.tsx` — global search UI for `GET /search` (see `backend/app/search_service.py`). `useSearch()`'s `runSearch(query)` fires on demand (form submit), not live-as-you-type. `SearchPage.tsx` groups the flat result list by `kind` into fixed-order French-labeled sections (Tâches, Rendez-vous, Fichiers, Mémoire, Chat), each a simple title+snippet list; a kind with no results that search just omits its section rather than showing it empty.
- `frontend/Dockerfile` — multi-stage build: `npm run build` then serves the static `dist/` via nginx. `VITE_API_URL` is a **build-time** arg (baked into the static bundle) since it's a browser-facing URL — it must point at the backend's published host port (e.g. `http://localhost:8000`), not an internal Docker network name.

The dockerized frontend has no published host port — it's on `infra-net` and reached through the Infra repo's shared NGINX at `jarvis.famillelallier.net` (see `nginx/conf.d/jarvis.conf` there), not `localhost:5173`. `localhost:5173` is only for the undockerized `npm run dev` flow below.

### Batch worker (`batch/`)

A long-running Python worker lives in `batch/app/`, with an internal cron (no system crontab, no external job broker):

- `batch/app/main.py` — entrypoint. Starts telemetry, a stdlib health server, an `AsyncIOScheduler` (APScheduler) that runs each registered job on its own interval (plus once immediately on startup), and a long-lived background task consuming `jarvis.ingest.requested` off RabbitMQ (see "Ingestion" below). Waits on `SIGTERM`/`SIGINT` for graceful shutdown, cancelling that consumer task alongside `scheduler.shutdown()`.
- `batch/app/jobs/` — one module per job, registered in `batch/app/jobs/__init__.py`'s `registered_jobs()`:
  - `heartbeat.py` — pings Postgres, counts MinIO objects, logs the result. Skeleton example.
  - `ingest_trigger.py` — checks Postgres for `StoredFile` rows with `ingested_at IS NULL`; if any exist, starts the (normally stopped) `jarvis-ingest` container via `app/docker_ingest.py`, skipping if it's already running. This periodic poll is a fallback safety net alongside the RabbitMQ-driven trigger below — either path can start the same container.
- `batch/app/docker_ingest.py` — docker-py helpers (`start_container`, `wait_container`) against `/var/run/docker.sock`, shared by `ingest_trigger.py` (poll path) and `ingest_consumer.py` (RabbitMQ path).
- `batch/app/ingest_consumer.py` — handles `jarvis.ingest.requested` messages (published by `backend/app/routers/files.py`'s `POST /files/{id}/ingest`): starts `jarvis-ingest`, blocks on `wait_container` for its exit code, then publishes `jarvis.ingest.completed` so the backend can relay it to the browser. See "Ingestion" below.
- `batch/app/healthserver.py` + `batch/app/health_state.py` — a minimal stdlib `GET /health` endpoint (no FastAPI/uvicorn) reporting whether the last job run succeeded; this is what Docker Compose's `healthcheck:` probes, since "the process is alive" alone doesn't prove the scheduler is actually ticking.
- `batch/app/config.py`, `batch/app/db.py`, `batch/app/storage.py` — thin wrappers around `jarvis_shared` (see "Shared package" above); `batch/app/telemetry.py` stays independently duplicated (OTEL setup differs slightly per container).
- `batch/tests/` — same fake-settings-monkeypatch pattern as `backend/tests/conftest.py`, so `make test-batch` needs no live Postgres/MinIO/Docker/RabbitMQ.

No HTTP API surface besides `/health` — jobs that need to expose data should write to Postgres or MinIO for `backend`/`frontend` to read, not serve their own routes. The RabbitMQ consumer is the one exception to "no inbound surface": it's a message queue subscription, not an HTTP route.

**Security note on `ingest_trigger`:** `batch` no longer mounts `/var/run/docker.sock` directly. Instead, `docker-compose.yml`'s `docker-socket-proxy` service (`tecnativa/docker-socket-proxy`) holds that mount, and `batch` talks to it over `docker_proxy_url` (`batch/app/config.py`, default `tcp://docker-socket-proxy:2375`, consumed by `batch/app/docker_ingest.py`'s `DockerClient`) across an isolated `docker-proxy-net` network shared by only those two services — not reachable from `infra-net` or anything else in the compose project. The proxy is configured with `CONTAINERS=1` and `POST=1`, which grants list/inspect/start/stop (and other lifecycle POST calls) on the `CONTAINERS` API resource for *any* container on the host, not scoped to `jarvis-ingest` specifically — the proxy filters by API resource, not by container name or individual verb, so this is coarser than "`containers.start`/`get` on `jarvis-ingest` only" would ideally be. It's still a real reduction from the previous state: batch can no longer create new containers with arbitrary mounts, exec into containers, read images/volumes/networks, or reach any other Docker API resource (e.g. `EXEC`, `IMAGES`, `NETWORKS`, `VOLUMES` remain unset/disabled). `batch`'s Dockerfile running as non-root (`appuser`) is still not what provides this scoping — the proxy's own env-var allowlist is.

### Ingestion (`ingest/`)

A normally-stopped, one-shot Python container that does the actual RAG file-ingestion work — chunking and embedding files uploaded through the backend's Files feature (`backend/app/routers/files.py`) so they become retrievable later.

- `ingest/app/main.py` — entrypoint: runs one ingestion pass, exits 0 on full success or 1 if anything failed (so `docker inspect`/`docker compose ps` shows a distinguishable exit code). No HTTP surface, no scheduler of its own — `batch/app/jobs/ingest_trigger.py` starts it.
- `ingest/app/pipeline.py` — orchestration: finds `StoredFile` rows with `ingested_at IS NULL`, skips (but still stamps) unsupported content-types, pulls bytes from MinIO, chunks, embeds, writes `FileChunk` rows, stamps `ingested_at`. Commits per-file so a crash mid-run only leaves the *current* file unprocessed, not ones already done.
- `ingest/app/chunking.py` — naive fixed-size character windows with overlap (`INGEST_CHUNK_SIZE_CHARS`/`INGEST_CHUNK_OVERLAP_CHARS`). No tokenizer, no sentence-awareness — deliberately minimal until retrieval quality can actually be measured.
- `ingest/app/embeddings.py` — calls LM Studio's OpenAI-compatible `/v1/embeddings` endpoint (`EMBEDDING_LMSTUDIO_BASE_URL`/`EMBEDDING_LMSTUDIO_MODEL` — **separate** from backend's `LMSTUDIO_MODEL`, which is a chat model, not an embedding model), batching all of a file's chunks into one request.
- `ingest/app/image_description.py` — calls LM Studio's OpenAI-compatible `/v1/chat/completions` endpoint with a vision-capable model (`VISION_LMSTUDIO_BASE_URL`/`VISION_LMSTUDIO_MODEL` — **separate** again, since not every chat model accepts image input) to get a text description of an image's content, sent as a base64 `data:` URL. That description is what actually gets chunked and embedded for an image file — there's no text to extract from raw pixels otherwise. `describe_image()` takes an optional `prompt` override (default `vision_description_prompt`); `describe_pdf_pages()` calls it once per page with `pdf_ocr_prompt` instead (a transcription-focused prompt) and joins the per-page results under `[Page N]` headers — see the scanned-PDF fallback below.
- `ingest/app/pdf_render.py` — `render_pdf_pages_to_png()` rasterizes up to `pdf_ocr_max_pages` pages of a PDF to PNG bytes via `pypdfium2`/Pillow, feeding the scanned-PDF vision fallback below. Raises `PdfRenderError` if the PDF can't be opened/rendered.
- `ingest/app/db.py` — the one container that passes `register_vector_codec=True` to `jarvis_shared.db.make_engine()`, since it's the only one reading/writing `FileChunk.embedding`.
- `ingest/tests/` — chunking is pure-function tested; embeddings and image description mock `httpx`; pdf_render exercises `pypdfium2` directly against real (blank) PDF bytes; the pipeline test uses a real in-memory SQLite DB (pgvector's `Vector` type works fine there for basic DDL/insert/select) with MinIO and the embeddings/description/render calls mocked. No live Postgres/MinIO/LM Studio/Docker needed.

**Text extraction scope:** plainly-text `content_type`s (`text/*`, `application/json`, `.md`/`.txt` fallback by extension), PDF (`application/pdf`, `.pdf` fallback by extension, via `pypdf`), and images (`image/*`, common extension fallback) are all chunked and embedded. For images, the vision model's description text stands in for extracted text — so an image becomes findable by what it depicts, not by any text baked into its pixels. A vision-model failure (LM Studio unreachable, bad response) is treated as retriable, the same as an embedding failure — the file is left unstamped and retried on the next trigger, since restarting/reloading LM Studio can fix it. Other binary formats (DOCX) are skipped-but-stamped (`ingested_at` still gets set, so `ingest_trigger` doesn't loop forever retrying a file it can never process) — extracting text from those is a deliberately deferred follow-up. A PDF `pypdf` can't parse at all (corrupt/unsupported encoding) is likewise skipped-but-stamped rather than retried forever, since a retry won't fix a malformed file.

**Scanned-PDF vision fallback:** `pypdf` text extraction (`extract_text()`) is always tried first for a PDF. Only when that comes back empty — a scanned page with no text layer — does `process_file()` (`ingest/app/pipeline.py`) fall back to `render_pdf_pages_to_png()` + `describe_pdf_pages()`, effectively OCR-via-vision-model. A PDF with an extractable text layer never touches the vision model. A render or vision-model failure on that fallback path is retriable (same as an image-description failure), not skip-and-stamp, since a later retry (e.g. after restarting LM Studio) can still succeed.

**Power-up mechanics:** `docker-compose.yml`'s `ingest` service has `restart: "no"` and a fixed `container_name: jarvis-ingest`. It runs once per start and exits, so between triggers it just sits "Exited" — there's no polling loop or idle process to manage.

**On-demand trigger via RabbitMQ.** Besides `batch`'s periodic poll (above), a user can trigger ingestion for a specific file from the web portal: `FilesPage.tsx`'s "Ingérer" button calls `POST /files/{id}/ingest`, which publishes to the `jarvis.ingest.requested` queue (`backend/app/routers/files.py`). `batch/app/ingest_consumer.py` consumes that, starts `jarvis-ingest`, blocks on its exit via `docker-py`'s `container.wait()`, then publishes to `jarvis.ingest.completed`. `backend/app/main.py` consumes *that* queue in its own background task and relays each message over the `GET /ws/ingest-status` WebSocket, which `useFiles.ts` listens on to refresh the file list live. `ingest` itself is unaware of RabbitMQ — `batch` observes its completion externally via the Docker API, not a message `ingest` sends itself. Since `ingest`'s pipeline always processes *every* pending file in one pass, the completion message means "an ingest pass just finished," not "only this file changed" — the frontend reacts by reloading the whole list.

RabbitMQ itself is **already provisioned in the Infra repo** (`rabbitmq:4-management`, on `infra-net`, reachable at `rabbitmq:5672`) — same "shared root credential, no per-app provisioning yet" situation as MinIO. `RABBITMQ_USER`/`RABBITMQ_PASSWORD` in this repo's `.env` must match `RABBITMQ_DEFAULT_USER`/`RABBITMQ_DEFAULT_PASS` in Infra's `.env`; no Infra-repo changes are needed to use this feature.

### Database: uses the Infra repo's Postgres

Neither the backend, batch worker, nor ingest container runs its own Postgres. All three connect to the Postgres instance managed in the sibling `Infra` repo (`/Users/nicolaslallier/Claude/Infra`), over an external Docker network called `infra-net`, at hostname `postgres:5432`.

Infra reserves this app as `jarvis`: database `jarvis`, role `jarvis`, password in the `JARVIS_DB_PASSWORD` env var (must match between Infra's `.env` and this repo's `.env`). See Infra's own README/CLAUDE.md for the full provisioning convention (`APP_DATABASES`, `postgres/initdb/10-provision-apps.sh`).

**Prerequisite before running this backend:** the `jarvis` DB/role must exist in Infra's running Postgres cluster.
- Infra stack not started yet: set `JARVIS_DB_PASSWORD` in Infra's `.env`, then `make up` in the Infra repo.
- Infra stack already running: `make provision-app app=jarvis` in the Infra repo.

**Schema management — `create_all` plus Alembic.** The original tables (`items`, `tasks`, `chat_sessions`, `chat_messages`, `folders`, `files`) are still created via `Base.metadata.create_all` in `backend/app/main.py`'s startup lifespan, kept for backwards compatibility. Alembic (`shared/jarvis_shared/migrations/`) was introduced for everything past that baseline, because adding a Postgres **extension** and altering an existing table are both things `create_all` cannot express at all. Run migrations manually with `make migrate` — deliberately not automatic on container boot, since three containers restarting simultaneously and all racing `alembic upgrade head` would be worse than a manual step. A fresh database should be stamped at the baseline revision (`alembic stamp 0001` from `shared/`) before the first real `make migrate`.

**Prerequisite before running ingestion (or chat memory):** the `vector` extension (pgvector) must be available in Infra's Postgres before `make migrate` runs.
- If Infra's Postgres image isn't already pgvector-capable, that's an Infra-repo image swap — this repo can't change what image Infra runs.
- A Postgres superuser must be able to run `CREATE EXTENSION IF NOT EXISTS vector` against the `jarvis` database — the `jarvis` app role likely lacks that privilege, the same reasoning as why db/role provisioning happens via Infra's superuser `initdb` scripts, not this repo. Whether this becomes part of Infra's `postgres/initdb/10-provision-apps.sh` or a one-off manual step is an Infra-repo decision.
- `shared/jarvis_shared/migrations/versions/0003_pgvector_ingestion.py` issues the `CREATE EXTENSION` statement itself as a convenience, but will fail with a clear permissions error if Infra hasn't done its part — that failure is the signal to go make the Infra-repo change first, not a bug in the migration. (`files.ingested_at`, which `GET /files` always selects, was split out into `0002_files_ingested_at.py` so the Files feature isn't blocked on this Infra prerequisite too.) `0004_memories.py` adds the `memories` table backend/app/memory.py reads/writes (see the Backend section above) — it depends on the same `vector` extension but not on `ingest`/`file_chunks`, so it only needs 0003's extension to already exist, not the ingestion feature itself to be in use. `0008_baseline_tables_safety_net.py` adds a purely additive `CREATE TABLE IF NOT EXISTS` safety net for the 6 `create_all`-managed tables above, so `alembic upgrade head` alone can bootstrap a database that never ran `create_all` at all (e.g. CI/staging) — it's a no-op on every existing database and deliberately doesn't retrofit `IF NOT EXISTS` guards into 0002/0006 to fully retire `create_all`, since that's real surgery on migrations that may already have run against the live homelab Postgres.

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

# shared/backend/batch/ingest tests all mock settings/db/minio/rabbitmq/
# docker/LM Studio, so none of them need a live Postgres, MinIO, RabbitMQ,
# or Docker daemon —
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
