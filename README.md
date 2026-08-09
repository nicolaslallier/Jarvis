# Jarvis

- `backend/` — FastAPI API (see [CLAUDE.md](CLAUDE.md))
- `frontend/` — React + Vite web portal (see [CLAUDE.md](CLAUDE.md))

Run `docker compose up -d` from the repo root to start both (requires the sibling Infra repo's Postgres stack + `infra-net` already running).

## Observability

The API exposes Prometheus metrics at `GET /metrics` and (when
`OTEL_EXPORTER_OTLP_ENDPOINT` is set) sends OpenTelemetry traces to the
Infra Alloy receiver (`http://alloy:4318` by default in Compose). The
`api` service publishes a stable Docker network alias `jarvis-api` on
`infra-net` so Infra's Prometheus can scrape it.

After changing observability deps, rebuild the API image:

```bash
docker compose build api && docker compose up -d api
```

Full dashboard: Grafana → **Jarvis** (`https://grafana.infra.famillelallier.net`).
