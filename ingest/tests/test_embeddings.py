from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import Settings
from app.embeddings import EmbeddingError, embed_chunks


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://x/y",
        embedding_lmstudio_base_url="http://lmstudio.test",
        embedding_lmstudio_model="test-model",
    )


@pytest.mark.asyncio
async def test_embed_chunks_empty_input_returns_empty_without_a_request():
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        result = await embed_chunks(_settings(), [])
    assert result == []
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_embed_chunks_success_sorts_by_index_and_sends_expected_request():
    canned_response = httpx.Response(
        200,
        json={
            "data": [
                {"index": 1, "embedding": [0.2, 0.3]},
                {"index": 0, "embedding": [0.1, 0.1]},
            ]
        },
        request=httpx.Request("POST", "http://lmstudio.test/v1/embeddings"),
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=canned_response)) as mock_post:
        result = await embed_chunks(_settings(), ["a", "b"])

    assert result == [[0.1, 0.1], [0.2, 0.3]]
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"model": "test-model", "input": ["a", "b"]}


@pytest.mark.asyncio
async def test_embed_chunks_raises_on_request_error():
    async def _raise(*args, **kwargs):
        raise httpx.RequestError("boom", request=httpx.Request("POST", "http://lmstudio.test"))

    with patch("httpx.AsyncClient.post", new=_raise):
        with pytest.raises(EmbeddingError, match="Could not reach LM Studio"):
            await embed_chunks(_settings(), ["a"])


@pytest.mark.asyncio
async def test_embed_chunks_raises_on_non_200_status():
    canned_response = httpx.Response(
        500, text="boom", request=httpx.Request("POST", "http://lmstudio.test/v1/embeddings")
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=canned_response)):
        with pytest.raises(EmbeddingError, match="LM Studio returned 500"):
            await embed_chunks(_settings(), ["a"])


@pytest.mark.asyncio
async def test_embed_chunks_raises_on_unexpected_response_shape():
    canned_response = httpx.Response(
        200,
        json={"unexpected": True},
        request=httpx.Request("POST", "http://lmstudio.test/v1/embeddings"),
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=canned_response)):
        with pytest.raises(EmbeddingError, match="Unexpected response shape"):
            await embed_chunks(_settings(), ["a"])
