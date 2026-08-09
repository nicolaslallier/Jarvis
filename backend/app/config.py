from functools import lru_cache

from jarvis_shared.config import SharedSettings


class Settings(SharedSettings):
    cors_origins: str = "*"
    otel_service_name: str = "jarvis-api"
    # LM Studio's OpenAI-compatible server. Since the backend usually runs
    # inside Docker, `127.0.0.1` would point at the container itself, not
    # the host machine running LM Studio — use `host.docker.internal`
    # instead (works out of the box on Docker Desktop for Mac/Windows; the
    # compose file adds the Linux `host-gateway` mapping for portability).
    lmstudio_base_url: str = "http://host.docker.internal:1234"
    lmstudio_model: str = "google/gemma-4-26b-a4b-qat"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
