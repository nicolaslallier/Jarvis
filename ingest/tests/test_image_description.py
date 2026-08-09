from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import Settings
from app.image_description import ImageDescriptionError, describe_image


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://x/y",
        vision_lmstudio_base_url="http://lmstudio.test",
        vision_lmstudio_model="test-vision-model",
    )


@pytest.mark.asyncio
async def test_describe_image_success_sends_data_url_and_returns_content():
    canned_response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "a red bicycle leaning against a brick wall"}}]},
        request=httpx.Request("POST", "http://lmstudio.test/v1/chat/completions"),
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=canned_response)) as mock_post:
        result = await describe_image(_settings(), "photo.png", "image/png", b"fake-bytes")

    assert result == "a red bicycle leaning against a brick wall"
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["model"] == "test-vision-model"
    content = kwargs["json"]["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_describe_image_guesses_mime_type_from_extension_when_content_type_missing():
    canned_response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "a photo"}}]},
        request=httpx.Request("POST", "http://lmstudio.test/v1/chat/completions"),
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=canned_response)) as mock_post:
        await describe_image(_settings(), "photo.jpg", None, b"fake-bytes")

    _, kwargs = mock_post.call_args
    content = kwargs["json"]["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_describe_image_raises_on_request_error():
    async def _raise(*args, **kwargs):
        raise httpx.RequestError("boom", request=httpx.Request("POST", "http://lmstudio.test"))

    with patch("httpx.AsyncClient.post", new=_raise):
        with pytest.raises(ImageDescriptionError, match="Could not reach LM Studio"):
            await describe_image(_settings(), "photo.png", "image/png", b"fake-bytes")


@pytest.mark.asyncio
async def test_describe_image_raises_on_non_200_status():
    canned_response = httpx.Response(
        500, text="boom", request=httpx.Request("POST", "http://lmstudio.test/v1/chat/completions")
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=canned_response)):
        with pytest.raises(ImageDescriptionError, match="LM Studio returned 500"):
            await describe_image(_settings(), "photo.png", "image/png", b"fake-bytes")


@pytest.mark.asyncio
async def test_describe_image_raises_on_unexpected_response_shape():
    canned_response = httpx.Response(
        200,
        json={"unexpected": True},
        request=httpx.Request("POST", "http://lmstudio.test/v1/chat/completions"),
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=canned_response)):
        with pytest.raises(ImageDescriptionError, match="Unexpected response shape"):
            await describe_image(_settings(), "photo.png", "image/png", b"fake-bytes")
