from unittest.mock import patch

import httpx

from app.db import async_session
from app.main import app
from app.memory import (
    RetrievedMemory,
    format_memory_context,
    parse_extracted_facts,
    store_memories,
)
from app.routers import memory as memory_router

EMBED_URL = "http://lmstudio.test/v1/embeddings"

# /memories is registered on `app` by app/main.py, which is owned by a
# separate change in this multi-agent worktree and deliberately not touched
# here. Include it defensively so these tests pass whether or not that
# wiring has landed yet — harmless if main.py already did it too, since
# FastAPI just matches the first registration for a given path+method.
if not any(getattr(route, "path", None) == "/memories" for route in app.router.routes):
    app.include_router(memory_router.router)


class _FakeEmbeddingClient:
    """Minimal stand-in for the httpx.AsyncClient app/routers/memory.py's
    _embed_text opens — only .post() is needed, unlike test_chat.py's fuller
    fake client which also handles streaming chat-completion calls."""

    def __init__(self, response: httpx.Response | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> "_FakeEmbeddingClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs.get("json")))
        if self._error:
            raise self._error
        return self._response


def _embedding_response(vector: list[float], status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"data": [{"index": 0, "embedding": vector}]},
        request=httpx.Request("POST", EMBED_URL),
    )


async def _seed_memory(content: str, embedding: list[float] | None = None) -> None:
    """Inserts a memory the same way app/routers/chat.py's extraction flow
    does (via store_memories), so list/update/delete tests have a real row
    to work with. There's no creation endpoint — memories are only ever
    created from chat exchanges."""
    async with async_session() as db:
        await store_memories(db, session_id=None, facts=[content], embeddings=[embedding or [0.1, 0.2]])


def test_parse_extracted_facts_plain_array():
    raw = '["The user\'s dog is named Biscuit.", "The user works remotely on Fridays."]'
    assert parse_extracted_facts(raw) == [
        "The user's dog is named Biscuit.",
        "The user works remotely on Fridays.",
    ]


def test_parse_extracted_facts_empty_array():
    assert parse_extracted_facts("[]") == []


def test_parse_extracted_facts_wrapped_in_prose():
    raw = 'Sure, here are the facts:\n["The user prefers morning meetings."]\nLet me know if needed.'
    assert parse_extracted_facts(raw) == ["The user prefers morning meetings."]


def test_parse_extracted_facts_wrapped_in_code_fence():
    raw = '```json\n["The user\'s anniversary is June 12th."]\n```'
    assert parse_extracted_facts(raw) == ["The user's anniversary is June 12th."]


def test_parse_extracted_facts_no_brackets_returns_empty():
    assert parse_extracted_facts("There's nothing worth remembering here.") == []


def test_parse_extracted_facts_invalid_json_returns_empty():
    assert parse_extracted_facts("[not valid json,,,]") == []


def test_parse_extracted_facts_no_array_present_returns_empty():
    assert parse_extracted_facts('{"fact": "not an array"}') == []


def test_parse_extracted_facts_drops_blank_entries():
    raw = '["The user likes tea.", "  ", ""]'
    assert parse_extracted_facts(raw) == ["The user likes tea."]


def test_format_memory_context_renders_bulleted_facts():
    memories = [
        RetrievedMemory(id=1, content="The user's dog is named Biscuit.", distance=0.01),
        RetrievedMemory(id=2, content="The user works remotely on Fridays.", distance=0.05),
    ]
    context = format_memory_context(memories)
    assert "- The user's dog is named Biscuit." in context
    assert "- The user works remotely on Fridays." in context


# --- GET/PATCH/DELETE /memories (app/routers/memory.py) -------------------


async def test_list_memories_returns_most_recent_first(client):
    await _seed_memory("The user's dog is named Biscuit.")
    await _seed_memory("The user works remotely on Fridays.")

    response = await client.get("/memories")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    # Most-recent-first (id DESC): the second fact seeded comes first.
    assert body[0]["content"] == "The user works remotely on Fridays."
    assert body[1]["content"] == "The user's dog is named Biscuit."
    for item in body:
        assert set(item.keys()) == {"id", "content", "session_id", "created_at"}


async def test_list_memories_empty(client):
    response = await client.get("/memories")

    assert response.status_code == 200
    assert response.json() == []


async def test_update_memory_reembeds_and_persists_new_content(client):
    await _seed_memory("The user's dog is named Biscuit.", embedding=[0.1, 0.2])
    memory_id = (await client.get("/memories")).json()[0]["id"]

    fake_client = _FakeEmbeddingClient(response=_embedding_response([0.9, 0.9]))
    with patch("app.routers.memory.httpx.AsyncClient", return_value=fake_client):
        response = await client.patch(f"/memories/{memory_id}", json={"content": "The user's dog is named Rex."})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == memory_id
    assert body["content"] == "The user's dog is named Rex."
    assert fake_client.calls == [
        (EMBED_URL, {"model": "test-embedding-model", "input": ["The user's dog is named Rex."]})
    ]

    listed = (await client.get("/memories")).json()
    assert listed[0]["content"] == "The user's dog is named Rex."


async def test_update_memory_not_found_returns_404(client):
    fake_client = _FakeEmbeddingClient(response=_embedding_response([0.1]))
    with patch("app.routers.memory.httpx.AsyncClient", return_value=fake_client):
        response = await client.patch("/memories/999", json={"content": "no such memory"})

    assert response.status_code == 404


async def test_update_memory_embedding_failure_returns_502_and_leaves_content_unchanged(client):
    await _seed_memory("The user's dog is named Biscuit.")
    memory_id = (await client.get("/memories")).json()[0]["id"]

    fake_client = _FakeEmbeddingClient(response=_embedding_response([0.1], status_code=500))
    with patch("app.routers.memory.httpx.AsyncClient", return_value=fake_client):
        response = await client.patch(f"/memories/{memory_id}", json={"content": "corrupted attempt"})

    assert response.status_code == 502

    # The edit must not have gone through: a stale embedding after a silent
    # partial update would be worse than failing outright.
    listed = (await client.get("/memories")).json()
    assert listed[0]["content"] == "The user's dog is named Biscuit."


async def test_update_memory_embedding_network_error_returns_502(client):
    await _seed_memory("The user's dog is named Biscuit.")
    memory_id = (await client.get("/memories")).json()[0]["id"]

    fake_client = _FakeEmbeddingClient(error=httpx.ConnectError("connection refused"))
    with patch("app.routers.memory.httpx.AsyncClient", return_value=fake_client):
        response = await client.patch(f"/memories/{memory_id}", json={"content": "corrupted attempt"})

    assert response.status_code == 502


async def test_delete_memory_removes_it(client):
    await _seed_memory("The user's dog is named Biscuit.")
    memory_id = (await client.get("/memories")).json()[0]["id"]

    response = await client.delete(f"/memories/{memory_id}")

    assert response.status_code == 204
    assert (await client.get("/memories")).json() == []


async def test_delete_memory_not_found_returns_404(client):
    response = await client.delete("/memories/999")

    assert response.status_code == 404
