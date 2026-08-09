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

    # Same LM Studio embeddings endpoint ingest uses to embed file chunks
    # (see ingest/app/config.py) — reuses the EMBEDDING_LMSTUDIO_* env vars
    # so both containers stay pointed at the same model. A query embedded
    # with a different model than the chunks isn't comparable to them.
    embedding_lmstudio_base_url: str = "http://host.docker.internal:1234"
    embedding_lmstudio_model: str = "text-embedding-nomic-embed-text-v1.5"

    # How many file_chunks to retrieve as context per chat message.
    rag_top_k: int = 4

    # How many memories (see backend/app/memory.py) to retrieve as context
    # per chat message.
    memory_top_k: int = 6

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
