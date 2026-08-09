from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    cors_origins: str = "*"
    app_env: str = "development"
    # LM Studio's OpenAI-compatible server. Since the backend usually runs
    # inside Docker, `127.0.0.1` would point at the container itself, not
    # the host machine running LM Studio — use `host.docker.internal`
    # instead (works out of the box on Docker Desktop for Mac/Windows; the
    # compose file adds the Linux `host-gateway` mapping for portability).
    lmstudio_base_url: str = "http://host.docker.internal:1234"
    lmstudio_model: str = "google/gemma-4-26b-a4b-qat"
    # Empty disables OTEL (local/pytest). In Compose: http://alloy:4318
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "jarvis-api"

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
