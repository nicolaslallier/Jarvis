from functools import lru_cache

from jarvis_shared.config import SharedSettings


class Settings(SharedSettings):
    otel_service_name: str = "jarvis-batch"

    # How often (minutes) the internal scheduler runs registered jobs.
    batch_job_interval_minutes: int = 15

    # Port the stdlib health server listens on inside the container.
    batch_health_port: int = 8080

    # Fixed name of the ingest container (see docker-compose.yml's
    # `container_name: jarvis-ingest`) that ingest_trigger starts via the
    # Docker socket when there are unprocessed files.
    ingest_container_name: str = "jarvis-ingest"


@lru_cache
def get_settings() -> Settings:
    return Settings()
