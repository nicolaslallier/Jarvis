from functools import lru_cache

from jarvis_shared.config import SharedSettings


class Settings(SharedSettings):
    otel_service_name: str = "jarvis-ingest"

    # LM Studio's OpenAI-compatible server — same host.docker.internal
    # convention as backend/app/config.py's lmstudio_base_url, but a
    # SEPARATE model: backend's lmstudio_model is a chat model, and
    # embeddings need a model actually capable of producing embeddings.
    # Must match EMBEDDING_DIMENSIONS in jarvis_shared/models.py, or writes
    # to file_chunks will fail with a dimension mismatch.
    embedding_lmstudio_base_url: str = "http://host.docker.internal:1234"
    embedding_lmstudio_model: str = "text-embedding-nomic-embed-text-v1.5"

    # Naive fixed-size character chunking (see app/chunking.py) — no
    # tokenizer, no sentence-awareness, deliberately minimal until retrieval
    # quality can actually be measured.
    chunk_size_chars: int = 1000
    chunk_overlap_chars: int = 150


@lru_cache
def get_settings() -> Settings:
    return Settings()
