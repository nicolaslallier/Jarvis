from unittest.mock import patch

import pytest

from app import obsidian_service
from app.obsidian_service import ObsidianNotConfigured, ObsidianRequestError


class _FakeResponse:
    def __init__(self, status_code: int, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text

    def json(self):
        return self._json_body


class _FakeObsidianClient:
    """Stand-in for the httpx.AsyncClient app/obsidian_service.py opens per
    call. `response` is returned for every request regardless of
    method/url — each test only needs one call, so there's no need for the
    per-URL queueing test_chat.py's fake LM Studio client uses."""

    def __init__(self, response: _FakeResponse | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self) -> "_FakeObsidianClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def _call(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        if self._error is not None:
            raise self._error
        return self._response

    async def get(self, url, **kwargs):
        return await self._call("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self._call("POST", url, **kwargs)

    async def put(self, url, **kwargs):
        return await self._call("PUT", url, **kwargs)

    async def delete(self, url, **kwargs):
        return await self._call("DELETE", url, **kwargs)


def _patched(fake_client):
    return patch("app.obsidian_service.httpx.AsyncClient", return_value=fake_client)


@pytest.mark.asyncio
async def test_list_notes_returns_files():
    fake_client = _FakeObsidianClient(_FakeResponse(200, {"files": ["a.md", "Journal/"]}))
    with _patched(fake_client):
        files = await obsidian_service.list_notes()
    assert files == ["a.md", "Journal/"]
    method, url, kwargs = fake_client.calls[0]
    assert method == "GET"
    assert url == "http://obsidian.test:27123/vault/"
    assert kwargs["headers"]["Authorization"] == "Bearer test-obsidian-key"


@pytest.mark.asyncio
async def test_list_notes_subfolder_url_has_trailing_slash():
    fake_client = _FakeObsidianClient(_FakeResponse(200, {"files": []}))
    with _patched(fake_client):
        await obsidian_service.list_notes("Journal")
    _, url, _ = fake_client.calls[0]
    assert url == "http://obsidian.test:27123/vault/Journal/"


@pytest.mark.asyncio
async def test_read_note_returns_text_body():
    fake_client = _FakeObsidianClient(_FakeResponse(200, text="# Hello\n\nWorld"))
    with _patched(fake_client):
        content = await obsidian_service.read_note("Journal/2026-08-17.md")
    assert content == "# Hello\n\nWorld"
    _, url, _ = fake_client.calls[0]
    assert url == "http://obsidian.test:27123/vault/Journal/2026-08-17.md"


@pytest.mark.asyncio
async def test_read_note_missing_raises_request_error():
    fake_client = _FakeObsidianClient(_FakeResponse(404, text="not found"))
    with _patched(fake_client), pytest.raises(ObsidianRequestError):
        await obsidian_service.read_note("missing.md")


@pytest.mark.asyncio
async def test_search_notes_posts_query_as_params():
    results = [{"filename": "a.md", "score": 1.5, "matches": []}]
    fake_client = _FakeObsidianClient(_FakeResponse(200, results))
    with _patched(fake_client):
        got = await obsidian_service.search_notes("dentist", context_length=50)
    assert got == results
    method, url, kwargs = fake_client.calls[0]
    assert method == "POST"
    assert url == "http://obsidian.test:27123/search/simple/"
    assert kwargs["params"] == {"query": "dentist", "contextLength": 50}


@pytest.mark.asyncio
async def test_write_note_puts_content():
    fake_client = _FakeObsidianClient(_FakeResponse(200))
    with _patched(fake_client):
        await obsidian_service.write_note("Notes/idea.md", "some content")
    method, url, kwargs = fake_client.calls[0]
    assert method == "PUT"
    assert url == "http://obsidian.test:27123/vault/Notes/idea.md"
    assert kwargs["content"] == "some content"
    assert kwargs["headers"]["Content-Type"] == "text/markdown"


@pytest.mark.asyncio
async def test_append_note_posts_content():
    fake_client = _FakeObsidianClient(_FakeResponse(204))
    with _patched(fake_client):
        await obsidian_service.append_note("Journal/today.md", "more text")
    method, url, kwargs = fake_client.calls[0]
    assert method == "POST"
    assert url == "http://obsidian.test:27123/vault/Journal/today.md"
    assert kwargs["content"] == "more text"


@pytest.mark.asyncio
async def test_delete_note_calls_delete():
    fake_client = _FakeObsidianClient(_FakeResponse(200))
    with _patched(fake_client):
        await obsidian_service.delete_note("old.md")
    method, url, _ = fake_client.calls[0]
    assert method == "DELETE"
    assert url == "http://obsidian.test:27123/vault/old.md"


@pytest.mark.asyncio
async def test_unconfigured_raises_before_any_request():
    fake_settings = type(
        "S", (), {"obsidian_base_url": "http://obsidian.test:27123", "obsidian_api_key": ""}
    )()
    fake_client = _FakeObsidianClient(_FakeResponse(200, {"files": []}))
    with (
        patch("app.obsidian_service.get_settings", return_value=fake_settings),
        _patched(fake_client),
    ):
        with pytest.raises(ObsidianNotConfigured):
            await obsidian_service.list_notes()
    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_non_2xx_raises_request_error():
    fake_client = _FakeObsidianClient(_FakeResponse(500, text="boom"))
    with _patched(fake_client), pytest.raises(ObsidianRequestError):
        await obsidian_service.write_note("x.md", "content")
