import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.memory import RetrievedMemory
from app.rag import RetrievedChunk
from app.routers import chat as chat_module
from app.routers.chat import SECRETARY_SYSTEM_PROMPT, TOOLS

STREAM_URL = "http://lmstudio.test/v1/chat/completions"
EMBED_URL = "http://lmstudio.test/v1/embeddings"


def _settings(**overrides) -> SimpleNamespace:
    """A stand-in for the Settings object app.routers.chat.get_settings()
    returns, with every field the router reads. Tests patch
    app.routers.chat.get_settings to control just the fields they care
    about (e.g. chat_history_max_messages)."""
    base = {
        "lmstudio_base_url": "http://lmstudio.test",
        "lmstudio_model": "test-model",
        "embedding_lmstudio_base_url": "http://lmstudio.test",
        "embedding_lmstudio_model": "test-embedding-model",
        "rag_top_k": 4,
        "memory_top_k": 6,
        "calendar_upcoming_days": 7,
        "timezone": "America/Toronto",
        "chat_history_max_messages": 40,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


async def _drain_background_tasks() -> None:
    """Memory extraction and title generation now run as fire-and-forget
    asyncio tasks (see app/routers/chat.py's _fire_and_forget) so they never
    add latency to the response. By the time the SSE response has fully
    streamed back, those tasks are already registered in
    chat_module._background_tasks — this waits for them to finish so tests
    can assert on their side effects."""
    pending = [t for t in chat_module._background_tasks if not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        assert block.startswith("data:")
        events.append(json.loads(block[len("data:") :].strip()))
    return events


class _FakeStreamResponse:
    """Stand-in for the httpx.Response yielded by `async with
    client.stream(...) as response`, carrying canned SSE lines LM Studio
    would send for one streaming chat-completion call."""

    def __init__(self, status_code: int, lines: list[str], body: str = ""):
        self.status_code = status_code
        self._lines = lines
        self._body = body.encode()

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return self._body


class _FakeStreamContextManager:
    def __init__(self, response: _FakeStreamResponse):
        self._response = response

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._response

    async def __aexit__(self, *exc_info) -> bool:
        return False


class _FakeStreamContextManagerError:
    """Raises on __aenter__, like a real client.stream() call would if the
    connection itself fails (LM Studio unreachable)."""

    def __init__(self, error: Exception):
        self._error = error

    async def __aenter__(self):
        raise self._error

    async def __aexit__(self, *exc_info) -> bool:
        return False


class _FakeLMStudioClient:
    """Stand-in for the httpx.AsyncClient the chat router opens. Handles
    both .post() (still used for embeddings, memory extraction, and title
    generation, which are plain non-streaming calls) and .stream() (used
    for the chat-completion calls, which are now SSE-streamed).

    Each of post_responses/stream_responses maps a URL to either a single
    response (reused for every call to that URL) or a list (popped in
    order — needed when a message hits the same URL more than once, e.g.
    the tool-calling round trip or the tools-rejected fallback retry).
    """

    def __init__(self, post_responses=None, stream_responses=None):
        self._post_responses = dict(post_responses or {})
        self._stream_responses = dict(stream_responses or {})
        self.post_calls: list[tuple[str, dict]] = []
        self.stream_calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs.get("json")))
        return self._pop_or_reuse(self._post_responses, url, "POST")

    def stream(self, method, url, **kwargs):
        self.stream_calls.append((url, kwargs.get("json")))
        item = self._pop_or_reuse(self._stream_responses, url, "stream")
        if isinstance(item, Exception):
            return _FakeStreamContextManagerError(item)
        return _FakeStreamContextManager(item)

    @staticmethod
    def _pop_or_reuse(table: dict, url: str, kind: str):
        value = table.get(url)
        if value is None:
            raise AssertionError(f"no queued {kind} response for {url}")
        if isinstance(value, list):
            if not value:
                raise AssertionError(f"{kind} response queue exhausted for {url}")
            return value.pop(0)
        return value


def _embedding_response(vector: list[float]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": [{"index": 0, "embedding": vector}]},
        request=httpx.Request("POST", EMBED_URL),
    )


def _ok_response(content: str) -> httpx.Response:
    """A plain (non-streaming) chat-completion response, still used for the
    memory-extraction and title-generation calls."""
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
        request=httpx.Request("POST", STREAM_URL),
    )


def _content_stream(content: str) -> _FakeStreamResponse:
    lines = [
        "data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": content}}]}),
        "data: [DONE]",
    ]
    return _FakeStreamResponse(200, lines)


def _tool_call_stream(tool_calls: list[dict]) -> _FakeStreamResponse:
    """tool_calls: list of {"id", "function": {"name", "arguments"}} — the
    arguments string is streamed as a single delta chunk per call, which is
    enough to exercise the accumulation logic without needing a
    char-by-char breakdown."""
    lines = [
        "data: "
        + json.dumps(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": i,
                                    "id": call["id"],
                                    "type": "function",
                                    "function": {"name": call["function"]["name"], "arguments": ""},
                                }
                                for i, call in enumerate(tool_calls)
                            ]
                        },
                    }
                ]
            }
        )
    ]
    for i, call in enumerate(tool_calls):
        lines.append(
            "data: "
            + json.dumps(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {"index": i, "function": {"arguments": call["function"]["arguments"]}}
                                ]
                            },
                        }
                    ]
                }
            )
        )
    lines.append("data: [DONE]")
    return _FakeStreamResponse(200, lines)


def _rejected_stream(status_code: int, body: str) -> _FakeStreamResponse:
    return _FakeStreamResponse(status_code, [], body=body)


@pytest.mark.asyncio
async def test_create_session_default_title(client):
    response = await client.post("/chat/sessions", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New chat"
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_create_session_custom_title(client):
    response = await client.post("/chat/sessions", json={"title": "Trip planning"})
    assert response.status_code == 200
    assert response.json()["title"] == "Trip planning"


@pytest.mark.asyncio
async def test_list_sessions_ordered_by_most_recently_active(client):
    first = (await client.post("/chat/sessions", json={"title": "First"})).json()
    second = (await client.post("/chat/sessions", json={"title": "Second"})).json()

    fake_client = _FakeLMStudioClient(stream_responses={STREAM_URL: _content_stream("hi")})
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client):
        await client.post(f"/chat/sessions/{first['id']}/messages", json={"content": "hello"})

    response = await client.get("/chat/sessions")
    assert response.status_code == 200
    ids = [s["id"] for s in response.json()]
    assert ids == [first["id"], second["id"]]


@pytest.mark.asyncio
async def test_get_session_not_found(client):
    response = await client.get("/chat/sessions/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "chat session not found"


@pytest.mark.asyncio
async def test_delete_session(client):
    created = (await client.post("/chat/sessions", json={})).json()

    response = await client.delete(f"/chat/sessions/{created['id']}")
    assert response.status_code == 204

    response = await client.get(f"/chat/sessions/{created['id']}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_session_not_found(client):
    response = await client.delete("/chat/sessions/999999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_send_message_persists_history_and_streams_reply(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(stream_responses={STREAM_URL: _content_stream("Hi there")})
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)

    user_event = next(e for e in events if e["type"] == "user_message")
    assert user_event["message"]["role"] == "user"
    assert user_event["message"]["content"] == "hello"

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == "Hi there"

    done = next(e for e in events if e["type"] == "done")
    assert done["assistant_message"]["role"] == "assistant"
    assert done["assistant_message"]["content"] == "Hi there"
    assert done["session"]["title"] == "hello"

    detail = (await client.get(f"/chat/sessions/{session['id']}")).json()
    assert [m["content"] for m in detail["messages"]] == ["hello", "Hi there"]


@pytest.mark.asyncio
async def test_send_message_sends_full_history_to_lmstudio(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(stream_responses={STREAM_URL: _content_stream("first reply")})
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client):
        await client.post(f"/chat/sessions/{session['id']}/messages", json={"content": "one"})

    fake_client2 = _FakeLMStudioClient(stream_responses={STREAM_URL: _content_stream("second reply")})
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client2), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client2):
        await client.post(f"/chat/sessions/{session['id']}/messages", json={"content": "two"})

    _, sent_json = fake_client2.stream_calls[0]
    sent_messages = sent_json["messages"]
    assert sent_messages[0] == {"role": "system", "content": SECRETARY_SYSTEM_PROMPT}
    assert [m["content"] for m in sent_messages if m["role"] != "system"] == [
        "one",
        "first reply",
        "two",
    ]


@pytest.mark.asyncio
async def test_send_message_truncates_history_sent_to_model(client):
    """The full history is always persisted, but only the most recent
    chat_history_max_messages are sent to LM Studio, so a long session
    never overflows the local model's context window."""
    session = (await client.post("/chat/sessions", json={})).json()

    for content, reply in [("one", "r1"), ("two", "r2")]:
        fake_client = _FakeLMStudioClient(stream_responses={STREAM_URL: _content_stream(reply)})
        with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client):
            await client.post(f"/chat/sessions/{session['id']}/messages", json={"content": content})

    fake_client3 = _FakeLMStudioClient(stream_responses={STREAM_URL: _content_stream("r3")})
    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client3), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client3),
        patch("app.routers.chat.get_settings", return_value=_settings(chat_history_max_messages=2)),
    ):
        await client.post(f"/chat/sessions/{session['id']}/messages", json={"content": "three"})

    _, sent_json = fake_client3.stream_calls[0]
    sent_messages = [m for m in sent_json["messages"] if m["role"] != "system"]
    assert [m["content"] for m in sent_messages] == ["r2", "three"]


@pytest.mark.asyncio
async def test_send_message_session_not_found(client):
    response = await client.post("/chat/sessions/999999/messages", json={"content": "hello"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_send_message_unreachable_still_persists_user_message(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(
        stream_responses={STREAM_URL: httpx.ConnectError("connection refused")}
    )
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    error_event = next(e for e in events if e["type"] == "error")
    assert error_event["detail"] == "An internal error occurred while streaming the response."

    detail = (await client.get(f"/chat/sessions/{session['id']}")).json()
    assert [m["content"] for m in detail["messages"]] == ["hello"]


@pytest.mark.asyncio
async def test_send_message_upstream_error_status(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(
        stream_responses={
            STREAM_URL: [
                _rejected_stream(500, "internal error"),
                _rejected_stream(500, "internal error"),
            ]
        }
    )
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    error_event = next(e for e in events if e["type"] == "error")
    assert error_event["detail"] == "An internal error occurred while streaming the response."


@pytest.mark.asyncio
async def test_send_message_injects_rag_context_from_matching_chunks(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_chunks = [
        RetrievedChunk(
            file_id=1,
            filename="notes.txt",
            chunk_index=0,
            chunk_text="Paris is the capital of France.",
            distance=0.05,
        )
    ]
    fake_client = _FakeLMStudioClient(
        post_responses={EMBED_URL: _embedding_response([0.1, 0.2, 0.3])},
        stream_responses={STREAM_URL: _content_stream("Paris!")},
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=fake_chunks),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages",
            json={"content": "What is the capital of France?"},
        )

    assert response.status_code == 200
    done = next(e for e in _parse_sse(response.text) if e["type"] == "done")
    assert done["assistant_message"]["content"] == "Paris!"

    embed_url, embed_json = fake_client.post_calls[0]
    assert embed_url == EMBED_URL
    assert embed_json["input"] == ["What is the capital of France?"]

    _, sent_json = fake_client.stream_calls[0]
    sent_messages = sent_json["messages"]
    assert sent_messages[0] == {"role": "system", "content": SECRETARY_SYSTEM_PROMPT}
    assert sent_messages[1]["role"] == "system"
    assert sent_messages[2]["role"] == "system"
    assert "Paris is the capital of France." in sent_messages[2]["content"]
    assert sent_messages[-1] == {"role": "user", "content": "What is the capital of France?"}


@pytest.mark.asyncio
async def test_send_message_emits_sources_event_from_matching_chunks(client):
    """The frontend needs to show which files/excerpts backed a reply, so
    the raw RAG chunk list (not just the formatted context string folded
    into the system message) must also come through as its own SSE event,
    sent right after the `session` event and before any `delta`s."""
    session = (await client.post("/chat/sessions", json={})).json()

    fake_chunks = [
        RetrievedChunk(
            file_id=1,
            filename="notes.txt",
            chunk_index=0,
            chunk_text="Paris is the capital of France. " * 20,
            distance=0.05,
        ),
        RetrievedChunk(
            file_id=2,
            filename="atlas.pdf",
            chunk_index=3,
            chunk_text="France is in Europe.",
            distance=0.09,
        ),
    ]
    fake_client = _FakeLMStudioClient(
        post_responses={EMBED_URL: _embedding_response([0.1, 0.2, 0.3])},
        stream_responses={STREAM_URL: _content_stream("Paris!")},
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=fake_chunks),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages",
            json={"content": "What is the capital of France?"},
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)

    sources_event = next(e for e in events if e["type"] == "sources")
    assert sources_event["sources"] == [
        {
            "filename": "notes.txt",
            "chunk_index": 0,
            "excerpt": ("Paris is the capital of France. " * 20)[:200],
        },
        {"filename": "atlas.pdf", "chunk_index": 3, "excerpt": "France is in Europe."},
    ]

    # sources arrives after session but before any delta/done events.
    types = [e["type"] for e in events]
    assert types.index("sources") > types.index("session")
    assert types.index("sources") < types.index("delta")


@pytest.mark.asyncio
async def test_send_message_omits_sources_event_when_no_chunks_found(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(
        post_responses={EMBED_URL: _embedding_response([0.1, 0.2, 0.3])},
        stream_responses={STREAM_URL: _content_stream("hi there")},
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert not any(e["type"] == "sources" for e in events)


@pytest.mark.asyncio
async def test_send_message_skips_context_when_no_chunks_found(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(
        post_responses={EMBED_URL: _embedding_response([0.1, 0.2, 0.3])},
        stream_responses={STREAM_URL: _content_stream("hi there")},
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    _, sent_json = fake_client.stream_calls[0]
    assert sent_json["messages"][0] == {"role": "system", "content": SECRETARY_SYSTEM_PROMPT}
    assert sent_json["messages"][1]["role"] == "system"
    assert sent_json["messages"][2] == {"role": "user", "content": "hello"}
    assert len(sent_json["messages"]) == 3


@pytest.mark.asyncio
async def test_send_message_continues_when_rag_retrieval_fails(client):
    """RAG is a quality boost, not a chat dependency — a broken vector
    lookup (e.g. the pgvector extension not provisioned yet) must not stop
    the message from sending."""
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(
        post_responses={EMBED_URL: _embedding_response([0.1, 0.2, 0.3])},
        stream_responses={STREAM_URL: _content_stream("still works")},
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch(
            "app.routers.chat.fetch_relevant_chunks",
            side_effect=Exception("vector extension missing"),
        ),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    done = next(e for e in _parse_sse(response.text) if e["type"] == "done")
    assert done["assistant_message"]["content"] == "still works"
    _, sent_json = fake_client.stream_calls[0]
    assert sent_json["messages"][0] == {"role": "system", "content": SECRETARY_SYSTEM_PROMPT}
    assert sent_json["messages"][1]["role"] == "system"
    assert sent_json["messages"][2] == {"role": "user", "content": "hello"}
    assert len(sent_json["messages"]) == 3


@pytest.mark.asyncio
async def test_send_message_always_includes_secretary_persona(client):
    """The persona system prompt is sent even when there's no memory/RAG
    context at all — it isn't conditional on retrieval succeeding."""
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(stream_responses={STREAM_URL: _content_stream("hi")})
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    _, sent_json = fake_client.stream_calls[0]
    assert sent_json["messages"][0] == {"role": "system", "content": SECRETARY_SYSTEM_PROMPT}


@pytest.mark.asyncio
async def test_send_message_grounds_model_in_current_local_datetime(client):
    """Without a real "today" anchor, the model resolves relative dates
    (e.g. "tomorrow") against whatever date it last saw in training, which
    can be years stale. The anchor must be in the user's local timezone
    (TIMEZONE setting), not UTC, so "tonight" or "tomorrow" don't resolve
    against the wrong calendar day whenever local time has already crossed
    (or hasn't yet crossed) midnight UTC."""
    session = (await client.post("/chat/sessions", json={})).json()

    frozen_utc_noon = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)
    fake_client = _FakeLMStudioClient(stream_responses={STREAM_URL: _content_stream("hi")})
    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = frozen_utc_noon
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    _, sent_json = fake_client.stream_calls[0]
    datetime_message = sent_json["messages"][1]
    assert datetime_message["role"] == "system"
    # 2026-08-09T12:00:00Z is 08:00 in America/Toronto (EDT, UTC-4 in August).
    assert "2026-08-09T08:00:00-04:00" in datetime_message["content"]
    assert "Sunday, August 09, 2026" in datetime_message["content"]
    assert "America/Toronto" in datetime_message["content"]


@pytest.mark.asyncio
async def test_send_message_injects_memory_context_from_matching_memories(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_memories = [
        RetrievedMemory(id=1, content="The user's dog is named Biscuit.", distance=0.02)
    ]
    fake_client = _FakeLMStudioClient(
        post_responses={EMBED_URL: _embedding_response([0.1, 0.2, 0.3])},
        stream_responses={STREAM_URL: _content_stream("Biscuit says hi!")},
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
        patch("app.routers.chat.fetch_relevant_memories", return_value=fake_memories),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages",
            json={"content": "How's my dog doing?"},
        )

    assert response.status_code == 200
    _, sent_json = fake_client.stream_calls[0]
    sent_messages = sent_json["messages"]
    assert sent_messages[0] == {"role": "system", "content": SECRETARY_SYSTEM_PROMPT}
    assert sent_messages[1]["role"] == "system"
    assert sent_messages[2]["role"] == "system"
    assert "The user's dog is named Biscuit." in sent_messages[2]["content"]


@pytest.mark.asyncio
async def test_send_message_continues_when_memory_retrieval_fails(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(
        post_responses={EMBED_URL: _embedding_response([0.1, 0.2, 0.3])},
        stream_responses={STREAM_URL: _content_stream("still works")},
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
        patch(
            "app.routers.chat.fetch_relevant_memories",
            side_effect=Exception("memories table missing"),
        ),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    done = next(e for e in _parse_sse(response.text) if e["type"] == "done")
    assert done["assistant_message"]["content"] == "still works"


@pytest.mark.asyncio
async def test_send_message_stores_extracted_memories(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(
        post_responses={
            EMBED_URL: _embedding_response([0.1, 0.2, 0.3]),
            STREAM_URL: _ok_response("[unused: parse_extracted_facts is mocked]"),
        },
        stream_responses={STREAM_URL: _content_stream("Got it, noted!")},
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
        patch(
            "app.routers.chat.parse_extracted_facts",
            return_value=["The user's birthday is on March 3rd."],
        ),
        patch("app.routers.chat.store_memories", new_callable=AsyncMock) as mock_store,
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages",
            json={"content": "My birthday is March 3rd, remember that."},
        )
        assert response.status_code == 200
        await _drain_background_tasks()

    mock_store.assert_awaited_once()
    _, session_id, facts, embeddings = mock_store.call_args.args
    assert session_id == session["id"]
    assert facts == ["The user's birthday is on March 3rd."]
    assert embeddings == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_send_message_skips_storing_when_no_facts_extracted(client):
    """A plain "hello" shouldn't produce a memory row — the extraction
    model's real reply to small talk has no JSON array in it, and
    parse_extracted_facts (exercised for real here, not mocked) turns that
    into an empty list."""
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(
        post_responses={STREAM_URL: _ok_response("hi there")},
        stream_responses={STREAM_URL: _content_stream("hi there")},
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.store_memories", new_callable=AsyncMock) as mock_store,
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )
        assert response.status_code == 200
        await _drain_background_tasks()

    mock_store.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_continues_when_memory_extraction_fails(client):
    """Memory extraction is best-effort and off the critical path — a crash
    while parsing the extraction reply must not affect the chat response,
    which has already been sent by the time extraction even runs."""
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(stream_responses={STREAM_URL: _content_stream("hi there")})

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch(
            "app.routers.chat.parse_extracted_facts",
            side_effect=Exception("boom"),
        ),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )
        assert response.status_code == 200
        await _drain_background_tasks()

    done = next(e for e in _parse_sse(response.text) if e["type"] == "done")
    assert done["assistant_message"]["content"] == "hi there"


@pytest.mark.asyncio
async def test_send_message_generates_title_in_background(client):
    """The first message gets an instant fallback title (first N chars)
    synchronously, then a short LLM-generated title overwrites it once the
    background title-generation call completes."""
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(
        post_responses={STREAM_URL: _ok_response("Birthday reminder")},
        stream_responses={STREAM_URL: _content_stream("Sure, I'll remember that.")},
    )

    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages",
            json={"content": "Remember that my birthday is March 3rd"},
        )
        assert response.status_code == 200
        # The title-generation task runs concurrently with the main request
        # (fired at the top of send_message, not awaited) and can finish
        # before or after the streamed reply depending on scheduling — only
        # the eventual, drained state is deterministic.
        await _drain_background_tasks()

    detail = (await client.get(f"/chat/sessions/{session['id']}")).json()
    assert detail["title"] == "Birthday reminder"


@pytest.mark.asyncio
async def test_send_message_first_completion_call_offers_calendar_tools(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(stream_responses={STREAM_URL: _content_stream("hi there")})

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    _, completion_json = next(
        c for c in fake_client.stream_calls if c[0].endswith("/v1/chat/completions")
    )
    assert completion_json["tools"] == TOOLS
    assert completion_json["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_send_message_executes_calendar_tool_call(client):
    """Jarvis actually manages the calendar: a model reply containing a
    create_appointment tool call results in a real appointment row, and a
    follow-up completion call (carrying the tool result) produces the
    final user-visible reply."""
    session = (await client.post("/chat/sessions", json={})).json()

    tool_calls = [
        {
            "id": "call_1",
            "function": {
                "name": "create_appointment",
                "arguments": json.dumps(
                    {
                        "title": "Dentist",
                        "start_time": "2026-09-01T15:00:00+00:00",
                        "end_time": "2026-09-01T15:30:00+00:00",
                    }
                ),
            },
        }
    ]
    fake_client = _FakeLMStudioClient(
        stream_responses={
            STREAM_URL: [
                _tool_call_stream(tool_calls),
                _content_stream("Booked your dentist appointment for Sep 1 at 3pm."),
            ]
        }
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages",
            json={"content": "book me a dentist appointment sep 1 3-3:30pm"},
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    tool_call_event = next(e for e in events if e["type"] == "tool_call")
    assert tool_call_event["name"] == "create_appointment"
    done = next(e for e in events if e["type"] == "done")
    assert done["assistant_message"]["content"] == "Booked your dentist appointment for Sep 1 at 3pm."

    list_response = await client.get("/calendar/appointments")
    titles = [a["title"] for a in list_response.json()]
    assert "Dentist" in titles

    # First two completions calls are the tool-call round trip; a possible
    # third is the best-effort memory-extraction call that runs after
    # (unrelated to tool calling, and this fake client has no response
    # queued for it, so it fails harmlessly — see other memory tests).
    completion_calls = [c for c in fake_client.stream_calls if c[0].endswith("/v1/chat/completions")]
    assert len(completion_calls) >= 2
    assert completion_calls[0][1]["tools"] == TOOLS
    followup_payload = completion_calls[1][1]
    # The tool-calling loop offers tools again on the follow-up call too
    # (see MAX_TOOL_ITERATIONS) — it only stops once a reply comes back
    # without further tool calls.
    assert followup_payload["tools"] == TOOLS
    tool_message = next(m for m in followup_payload["messages"] if m["role"] == "tool")
    result = json.loads(tool_message["content"])
    assert result["appointment"]["title"] == "Dentist"


@pytest.mark.asyncio
async def test_send_message_executes_task_tool_call(client):
    """Same round trip as the calendar tool test above, but for the task
    tools: a create_task tool call results in a real task row."""
    session = (await client.post("/chat/sessions", json={})).json()

    tool_calls = [
        {
            "id": "call_1",
            "function": {
                "name": "create_task",
                "arguments": json.dumps({"title": "Buy corn", "priority": "high"}),
            },
        }
    ]
    fake_client = _FakeLMStudioClient(
        stream_responses={
            STREAM_URL: [
                _tool_call_stream(tool_calls),
                _content_stream('Added "Buy corn" to your tasks.'),
            ]
        }
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages",
            json={"content": "remind me to buy corn"},
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    tool_call_event = next(e for e in events if e["type"] == "tool_call")
    assert tool_call_event["name"] == "create_task"
    done = next(e for e in events if e["type"] == "done")
    assert done["assistant_message"]["content"] == 'Added "Buy corn" to your tasks.'

    list_response = await client.get("/tasks")
    titles = [t["title"] for t in list_response.json()]
    assert "Buy corn" in titles

    completion_calls = [c for c in fake_client.stream_calls if c[0].endswith("/v1/chat/completions")]
    assert len(completion_calls) >= 2
    followup_payload = completion_calls[1][1]
    tool_message = next(m for m in followup_payload["messages"] if m["role"] == "tool")
    result = json.loads(tool_message["content"])
    assert result["task"]["title"] == "Buy corn"
    assert result["task"]["priority"] == "high"


@pytest.mark.asyncio
async def test_send_message_falls_back_when_tools_rejected(client):
    """Not every LM Studio model/version supports tool calling — if the
    first (tools-enabled) streaming call fails outright, retry once without
    tools rather than failing the whole message send."""
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(
        stream_responses={
            STREAM_URL: [
                _rejected_stream(400, "tools not supported by this model"),
                _content_stream("plain reply"),
            ]
        }
    )

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client), patch("app.embeddings.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    done = next(e for e in events if e["type"] == "done")
    assert done["assistant_message"]["content"] == "plain reply"

    # First two completions calls are the tools-rejected retry round trip; a
    # possible third is the best-effort memory-extraction call afterward.
    completion_calls = [c for c in fake_client.stream_calls if c[0].endswith("/v1/chat/completions")]
    assert len(completion_calls) >= 2
    assert completion_calls[0][1]["tools"] == TOOLS
    assert "tools" not in completion_calls[1][1]
