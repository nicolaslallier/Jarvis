# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

A FastAPI backend lives in `app/`:

- `app/main.py` — FastAPI app, CORS middleware, router registration, startup lifespan (runs `Base.metadata.create_all`).
- `app/config.py` — `pydantic-settings`-based settings (`DATABASE_URL`, `CORS_ORIGINS`, `APP_ENV`), read from `.env`. Normalizes the `postgres://` scheme to `postgresql+asyncpg://` for SQLAlchemy.
- `app/db.py` — async SQLAlchemy engine/session setup, `get_db()` dependency, `check_connection()` health helper.
- `app/models.py` — SQLAlchemy ORM models (currently a minimal `Item` example).
- `app/schemas.py` — Pydantic request/response models.
- `app/routers/` — one `APIRouter` per resource (`health.py`, `items.py`).
- `tests/` — pytest + `httpx` async test client against the ASGI app directly (no live server needed).

No migrations tool yet — schema is created via `create_all` on startup. Add Alembic once the schema needs to evolve past this example.

### Database: uses the Infra repo's Postgres

This backend does **not** run its own Postgres. It connects to the Postgres instance managed in the sibling `Infra` repo (`/Users/nicolaslallier/Claude/Infra`), over an external Docker network called `infra-net`, at hostname `postgres:5432`.

Infra reserves this app as `jarvis`: database `jarvis`, role `jarvis`, password in the `JARVIS_DB_PASSWORD` env var (must match between Infra's `.env` and this repo's `.env`). See Infra's own README/CLAUDE.md for the full provisioning convention (`APP_DATABASES`, `postgres/initdb/10-provision-apps.sh`).

**Prerequisite before running this backend:** the `jarvis` DB/role must exist in Infra's running Postgres cluster.
- Infra stack not started yet: set `JARVIS_DB_PASSWORD` in Infra's `.env`, then `make up` in the Infra repo.
- Infra stack already running: `make provision-app app=jarvis` in the Infra repo.

## Build / run / test

```bash
# one-time: copy env template and set JARVIS_DB_PASSWORD to match Infra's .env
cp .env.example .env

# build and run (requires Infra's stack + infra-net already up)
docker compose build
docker compose up -d

# sanity check
curl http://localhost:8000/health
curl http://localhost:8000/docs

# tests (in-process ASGI client — no need to build this project's Docker
# image, but DATABASE_URL must point at a reachable Postgres, e.g. Infra's
# nginx passthrough at 127.0.0.1:5432)
pip install -r requirements-dev.txt
pytest
```

Note: `docker-compose.yml` here can't `depends_on` Infra's `postgres` service (it's a different Compose project) — start Infra's stack first.
