import httpx

from app.config import Settings

EMBEDDINGS_TIMEOUT_SECONDS = 120.0


class EmbeddingError(Exception):
    pass


async def embed_chunks(settings: Settings, chunks: list[str]) -> list[list[float]]:
    """Call LM Studio's OpenAI-compatible /v1/embeddings endpoint for a batch
    of chunks from the same file in one request."""
    if not chunks:
        return []

    try:
        async with httpx.AsyncClient(timeout=EMBEDDINGS_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.embedding_lmstudio_base_url}/v1/embeddings",
                json={"model": settings.embedding_lmstudio_model, "input": chunks},
            )
    except httpx.RequestError as exc:
        raise EmbeddingError(
            f"Could not reach LM Studio at {settings.embedding_lmstudio_base_url}: {exc}"
        ) from exc

    if response.status_code != 200:
        raise EmbeddingError(f"LM Studio returned {response.status_code}: {response.text}")

    data = response.json()
    try:
        items = sorted(data["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in items]
    except (KeyError, IndexError, TypeError) as exc:
        raise EmbeddingError("Unexpected response shape from LM Studio") from exc
