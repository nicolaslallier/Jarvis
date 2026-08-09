from pydantic_settings import BaseSettings, SettingsConfigDict


class SharedSettings(BaseSettings):
    """Fields common to every Jarvis container.

    Each container defines its own ``Settings`` subclass (see
    ``backend/app/config.py``, ``batch/app/config.py``, ``ingest/app/config.py``)
    that inherits from this and adds its own app-specific fields, rather than
    importing this class directly.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    app_env: str = "development"

    # Empty disables OTEL (local/pytest). In Compose: http://alloy:4318
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "jarvis"

    # MinIO (S3-compatible object storage) from the Infra repo's shared
    # stack. There's no per-app MinIO provisioning yet (unlike Postgres's
    # per-app DB/role), so minio_access_key/minio_secret_key must match
    # MINIO_ROOT_USER/MINIO_ROOT_PASSWORD in the Infra repo's .env for now.
    minio_endpoint: str = "http://minio:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "jarvis"

    @property
    def sqlalchemy_url(self) -> str:
        # Infra's documented connection string uses the `postgres://` scheme,
        # which SQLAlchemy doesn't recognize as a dialect on its own.
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
