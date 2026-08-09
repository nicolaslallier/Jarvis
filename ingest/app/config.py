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

    # LM Studio vision-capable chat model used to describe an image's
    # content in words — again a SEPARATE model from both of the above,
    # since embeddings are text-only and not every chat model accepts image
    # input. The description text is what actually gets chunked/embedded,
    # so image search works off of described content rather than pixels.
    vision_lmstudio_base_url: str = "http://host.docker.internal:1234"
    vision_lmstudio_model: str = "qwen/qwen3.6-35b-a3b"
    vision_description_prompt: str = (
        "Describe this image in detail for a search index: visible text, "
        "objects, people, setting, and any other identifying context."
    )

    # extract_text() is always tried first for a PDF (see app/pipeline.py).
    # Only when that comes back empty (a scanned page with no text layer) do
    # we rasterize pages and fall back to the vision model above, using a
    # transcription-focused prompt instead of vision_description_prompt.
    # pdf_ocr_max_pages bounds how many pages get sent through the vision
    # model per file, since that's one request per page.
    pdf_ocr_prompt: str = (
        "Transcribe all text visible on this scanned document page exactly "
        "as it appears. If there is no legible text, briefly describe the "
        "page's visual content instead."
    )
    pdf_ocr_max_pages: int = 20

    # Naive fixed-size character chunking (see app/chunking.py) — no
    # tokenizer, no sentence-awareness, deliberately minimal until retrieval
    # quality can actually be measured.
    chunk_size_chars: int = 1000
    chunk_overlap_chars: int = 150


@lru_cache
def get_settings() -> Settings:
    return Settings()
