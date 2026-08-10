"""Shared LM Studio embeddings call.

Extracted from app/routers/chat.py's private `_embed_text`, which used to be
the only caller — now also used by app/routers/memory.py's POST /memories
(journal notes) so there's a single copy of this ~10-line HTTP call instead
of one per caller.

Returns None (rather than raising) on any failure — network error, non-200
response, malformed body. That suits best-effort callers like chat.py's RAG/
memory retrieval directly. Callers that need to fail loudly instead (e.g.
POST /memories, PATCH /memories/{id}) should treat a None return as an error
themselves rather than silently dropping it.
"""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

EMBEDDING_TIMEOUT_SECONDS = 30.0


async def embed_text(text: str) -> list[float] | None:
    """Embeds `text` via LM Studio's OpenAI-compatible /v1/embeddings
    endpoint, using the configured EMBEDDING_LMSTUDIO_BASE_URL/MODEL (kept
    separate from the chat model — see backend's config.py)."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.embedding_lmstudio_base_url}/v1/embeddings",
                json={"model": settings.embedding_lmstudio_model, "input": [text]},
            )
        if response.status_code != 200:
            logger.warning("Embedding call returned %s", response.status_code)
            return None
        return response.json()["data"][0]["embedding"]
    except Exception:
        logger.warning("Embedding call failed", exc_info=True)
        return None
