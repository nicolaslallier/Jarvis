from unittest.mock import patch

import httpx
import pytest


class _FakeLMStudioClient:
    """Stand-in for the httpx.AsyncClient the chat router opens to call LM
    Studio. Patching httpx.AsyncClient.post directly would also break the
    ASGI test client fixture, since it's an httpx.AsyncClient too."""

    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, *args, **kwargs):
        if self._error is not None:
            raise self._error
        return self._response


@pytest.mark.asyncio
async def test_chat(client):
    mock_response = httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": "Hi there"}}]},
        request=httpx.Request("POST", "http://lmstudio.test/v1/chat/completions"),
    )
    fake_client = _FakeLMStudioClient(response=mock_response)
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            "/chat", json={"messages": [{"role": "user", "content": "hello"}]}
        )

    assert response.status_code == 200
    assert response.json()["message"] == {"role": "assistant", "content": "Hi there"}


@pytest.mark.asyncio
async def test_chat_unreachable(client):
    fake_client = _FakeLMStudioClient(error=httpx.ConnectError("connection refused"))
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            "/chat", json={"messages": [{"role": "user", "content": "hello"}]}
        )

    assert response.status_code == 502
    assert "Could not reach LM Studio" in response.json()["detail"]


@pytest.mark.asyncio
async def test_chat_upstream_error_status(client):
    mock_response = httpx.Response(
        500,
        text="internal error",
        request=httpx.Request("POST", "http://lmstudio.test/v1/chat/completions"),
    )
    fake_client = _FakeLMStudioClient(response=mock_response)
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            "/chat", json={"messages": [{"role": "user", "content": "hello"}]}
        )

    assert response.status_code == 502
    assert "LM Studio returned 500" in response.json()["detail"]
