# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

There is no application source code yet. The repo currently provides a Docker Compose environment: a PostgreSQL database (`db`) and a pgAdmin web UI (`pgadmin`), configured via `docker-compose.yml` and driven through the `Makefile`.

## Environment

Copy `.env.example` to `.env` and fill in real values (`.env` is git-ignored). Required vars: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `PGADMIN_DEFAULT_EMAIL`, `PGADMIN_DEFAULT_PASSWORD`.

Commands (via `make`):
- `make up` — start the environment (`docker compose up -d`)
- `make down` — stop it
- `make logs` — stream logs
- `make db-shell` — open a `psql` shell in the `db` container

pgAdmin is exposed at `http://localhost:8080`. Inside pgAdmin, register the Postgres server using host `db` (the Docker Compose service name) and port `5432` — containers on the same Compose network resolve each other by service name, not by external/LAN hostnames.

There is no application source code, build tooling, package manifest, or test suite yet. When the user starts adding code, update this file further to document real build/lint/test commands and the actual architecture as it emerges. Do not invent structure or tooling ahead of what's actually in the repo.
