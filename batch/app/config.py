from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    app_env: str = "development"

    # Empty disables OTEL (local/pytest). In Compose: http://alloy:4318
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "jarvis-batch"

    # MinIO (S3-compatible object storage) from the Infra repo's shared
    # stack — same convention as backend/app/config.py.
    minio_endpoint: str = "http://minio:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "jarvis"

    # How often (minutes) the internal scheduler runs registered jobs.
    batch_job_interval_minutes: int = 15

    # Port the stdlib health server listens on inside the container.
    batch_health_port: int = 8080

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
