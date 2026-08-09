import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.memory import RetrievedMemory
from app.rag import RetrievedChunk
from app.routers.chat import CALENDAR_TOOLS, SECRETARY_SYSTEM_PROMPT


class _RoutingFakeLMStudioClient:
    """Like _FakeLMStudioClient, but returns a different canned response per
    URL. Needed once a message triggers two outbound calls (embed the query,
    then complete the chat) that must be told apart."""

    def __init__(self, responses: dict[str, httpx.Response]):
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs.get("json")))
        return self._responses[url]


def _embedding_response(vector: list[float]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": [{"index": 0, "embedding": vector}]},
        request=httpx.Request("POST", "http://lmstudio.test/v1/embeddings"),
    )


class _FakeLMStudioClient:
    """Stand-in for the httpx.AsyncClient the chat router opens to call LM
    Studio. Patching httpx.AsyncClient.post directly would also break the
    ASGI test client fixture, since it's an httpx.AsyncClient too."""

    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.last_json = None
        # A single fake client instance is reused for every httpx.AsyncClient
        # call the request makes (embed query, chat completion, extract
        # memories, embed extracted facts), so `last_json` alone can't tell
        # them apart — `calls` keeps all of them in order.
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, *args, **kwargs):
        self.last_json = kwargs.get("json")
        self.calls.append(self.last_json)
        if self._error is not None:
            raise self._error
        return self._response


def _ok_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
        request=httpx.Request("POST", "http://lmstudio.test/v1/chat/completions"),
    )


def _tool_call_response(tool_calls: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"role": "assistant", "content": None, "tool_calls": tool_calls}}
            ]
        },
        request=httpx.Request("POST", "http://lmstudio.test/v1/chat/completions"),
    )


class _SequentialFakeLMStudioClient:
    """Like _RoutingFakeLMStudioClient, but supports multiple queued
    responses per URL — needed for the tool-calling round trip, which calls
    /v1/chat/completions twice (once to get the tool_calls, once more with
    the tool result to get the final natural-language reply)."""

    def __init__(self, responses: dict[str, list[httpx.Response]]):
        self._responses = {url: list(r) for url, r in responses.items()}
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs.get("json")))
        queue = self._responses.get(url)
        if not queue:
            raise AssertionError(f"no queued response for {url}")
        return queue.pop(0)


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

    fake_client = _FakeLMStudioClient(response=_ok_response("hi"))
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client):
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
async def test_send_message_persists_history_and_sets_title(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(response=_ok_response("Hi there"))
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["user_message"]["role"] == "user"
    assert body["user_message"]["content"] == "hello"
    assert body["assistant_message"]["role"] == "assistant"
    assert body["assistant_message"]["content"] == "Hi there"
    assert body["session"]["title"] == "hello"

    detail = (await client.get(f"/chat/sessions/{session['id']}")).json()
    assert [m["content"] for m in detail["messages"]] == ["hello", "Hi there"]


@pytest.mark.asyncio
async def test_send_message_sends_full_history_to_lmstudio(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(response=_ok_response("first reply"))
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client):
        await client.post(f"/chat/sessions/{session['id']}/messages", json={"content": "one"})

    fake_client2 = _FakeLMStudioClient(response=_ok_response("second reply"))
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client2):
        await client.post(f"/chat/sessions/{session['id']}/messages", json={"content": "two"})

    sent_messages = next(
        c["messages"]
        for c in fake_client2.calls
        if c.get("messages") and c["messages"][0]["content"] == SECRETARY_SYSTEM_PROMPT
    )
    assert [m["content"] for m in sent_messages if m["role"] != "system"] == [
        "one",
        "first reply",
        "two",
    ]


@pytest.mark.asyncio
async def test_send_message_session_not_found(client):
    response = await client.post("/chat/sessions/999999/messages", json={"content": "hello"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_send_message_unreachable_still_persists_user_message(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(error=httpx.ConnectError("connection refused"))
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 502
    assert "Could not reach LM Studio" in response.json()["detail"]

    detail = (await client.get(f"/chat/sessions/{session['id']}")).json()
    assert [m["content"] for m in detail["messages"]] == ["hello"]


@pytest.mark.asyncio
async def test_send_message_upstream_error_status(client):
    session = (await client.post("/chat/sessions", json={})).json()

    mock_response = httpx.Response(
        500,
        text="internal error",
        request=httpx.Request("POST", "http://lmstudio.test/v1/chat/completions"),
    )
    fake_client = _FakeLMStudioClient(response=mock_response)
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 502
    assert "LM Studio returned 500" in response.json()["detail"]


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
    responses = {
        "http://lmstudio.test/v1/embeddings": _embedding_response([0.1, 0.2, 0.3]),
        "http://lmstudio.test/v1/chat/completions": _ok_response("Paris!"),
    }
    fake_client = _RoutingFakeLMStudioClient(responses)

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=fake_chunks),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages",
            json={"content": "What is the capital of France?"},
        )

    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == "Paris!"

    embed_url, embed_json = next(c for c in fake_client.calls if c[0].endswith("/v1/embeddings"))
    assert embed_json["input"] == ["What is the capital of France?"]

    _, completion_json = next(c for c in fake_client.calls if c[0].endswith("/v1/chat/completions"))
    sent_messages = completion_json["messages"]
    assert sent_messages[0] == {"role": "system", "content": SECRETARY_SYSTEM_PROMPT}
    assert sent_messages[1]["role"] == "system"
    assert sent_messages[2]["role"] == "system"
    assert "Paris is the capital of France." in sent_messages[2]["content"]
    assert sent_messages[-1] == {"role": "user", "content": "What is the capital of France?"}


@pytest.mark.asyncio
async def test_send_message_skips_context_when_no_chunks_found(client):
    session = (await client.post("/chat/sessions", json={})).json()

    responses = {
        "http://lmstudio.test/v1/embeddings": _embedding_response([0.1, 0.2, 0.3]),
        "http://lmstudio.test/v1/chat/completions": _ok_response("hi there"),
    }
    fake_client = _RoutingFakeLMStudioClient(responses)

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    _, completion_json = next(c for c in fake_client.calls if c[0].endswith("/v1/chat/completions"))
    assert completion_json["messages"][0] == {"role": "system", "content": SECRETARY_SYSTEM_PROMPT}
    assert completion_json["messages"][1]["role"] == "system"
    assert completion_json["messages"][2] == {"role": "user", "content": "hello"}
    assert len(completion_json["messages"]) == 3


@pytest.mark.asyncio
async def test_send_message_continues_when_rag_retrieval_fails(client):
    """RAG is a quality boost, not a chat dependency — a broken vector
    lookup (e.g. the pgvector extension not provisioned yet) must not stop
    the message from sending."""
    session = (await client.post("/chat/sessions", json={})).json()

    responses = {
        "http://lmstudio.test/v1/embeddings": _embedding_response([0.1, 0.2, 0.3]),
        "http://lmstudio.test/v1/chat/completions": _ok_response("still works"),
    }
    fake_client = _RoutingFakeLMStudioClient(responses)

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
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
    assert response.json()["assistant_message"]["content"] == "still works"
    _, completion_json = next(c for c in fake_client.calls if c[0].endswith("/v1/chat/completions"))
    assert completion_json["messages"][0] == {"role": "system", "content": SECRETARY_SYSTEM_PROMPT}
    assert completion_json["messages"][1]["role"] == "system"
    assert completion_json["messages"][2] == {"role": "user", "content": "hello"}
    assert len(completion_json["messages"]) == 3


@pytest.mark.asyncio
async def test_send_message_always_includes_secretary_persona(client):
    """The persona system prompt is sent even when there's no memory/RAG
    context at all — it isn't conditional on retrieval succeeding."""
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(response=_ok_response("hi"))
    with patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    completion_call = next(
        c
        for c in fake_client.calls
        if c.get("messages") and c["messages"][0]["content"] == SECRETARY_SYSTEM_PROMPT
    )
    assert completion_call["messages"][0] == {"role": "system", "content": SECRETARY_SYSTEM_PROMPT}


@pytest.mark.asyncio
async def test_send_message_grounds_model_in_current_datetime(client):
    """Without a real "today" anchor, the model resolves relative dates
    (e.g. "tomorrow") against whatever date it last saw in training, which
    can be years stale. Every turn must inject the actual current date/time
    right after the persona prompt so the model — and any calendar tool
    calls it makes — use the real date."""
    session = (await client.post("/chat/sessions", json={})).json()

    frozen_now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)
    fake_client = _FakeLMStudioClient(response=_ok_response("hi"))
    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = frozen_now
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    completion_call = next(
        c
        for c in fake_client.calls
        if c.get("messages") and c["messages"][0]["content"] == SECRETARY_SYSTEM_PROMPT
    )
    datetime_message = completion_call["messages"][1]
    assert datetime_message["role"] == "system"
    assert "2026-08-09" in datetime_message["content"]
    assert "Sunday, August 09, 2026" in datetime_message["content"]


@pytest.mark.asyncio
async def test_send_message_injects_memory_context_from_matching_memories(client):
    session = (await client.post("/chat/sessions", json={})).json()

    fake_memories = [
        RetrievedMemory(id=1, content="The user's dog is named Biscuit.", distance=0.02)
    ]
    responses = {
        "http://lmstudio.test/v1/embeddings": _embedding_response([0.1, 0.2, 0.3]),
        "http://lmstudio.test/v1/chat/completions": _ok_response("Biscuit says hi!"),
    }
    fake_client = _RoutingFakeLMStudioClient(responses)

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
        patch("app.routers.chat.fetch_relevant_memories", return_value=fake_memories),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages",
            json={"content": "How's my dog doing?"},
        )

    assert response.status_code == 200
    _, completion_json = next(c for c in fake_client.calls if c[0].endswith("/v1/chat/completions"))
    sent_messages = completion_json["messages"]
    assert sent_messages[0] == {"role": "system", "content": SECRETARY_SYSTEM_PROMPT}
    assert sent_messages[1]["role"] == "system"
    assert sent_messages[2]["role"] == "system"
    assert "The user's dog is named Biscuit." in sent_messages[2]["content"]


@pytest.mark.asyncio
async def test_send_message_continues_when_memory_retrieval_fails(client):
    session = (await client.post("/chat/sessions", json={})).json()

    responses = {
        "http://lmstudio.test/v1/embeddings": _embedding_response([0.1, 0.2, 0.3]),
        "http://lmstudio.test/v1/chat/completions": _ok_response("still works"),
    }
    fake_client = _RoutingFakeLMStudioClient(responses)

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
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
    assert response.json()["assistant_message"]["content"] == "still works"


@pytest.mark.asyncio
async def test_send_message_stores_extracted_memories(client):
    session = (await client.post("/chat/sessions", json={})).json()

    responses = {
        "http://lmstudio.test/v1/embeddings": _embedding_response([0.1, 0.2, 0.3]),
        "http://lmstudio.test/v1/chat/completions": _ok_response("Got it, noted!"),
    }
    fake_client = _RoutingFakeLMStudioClient(responses)

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
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

    fake_client = _FakeLMStudioClient(response=_ok_response("hi there"))

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.store_memories", new_callable=AsyncMock) as mock_store,
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    mock_store.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_continues_when_memory_extraction_fails(client):
    """Memory extraction is best-effort — a crash while parsing the
    extraction reply must not take down an otherwise-successful chat send."""
    session = (await client.post("/chat/sessions", json={})).json()

    fake_client = _FakeLMStudioClient(response=_ok_response("hi there"))

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
        patch(
            "app.routers.chat.parse_extracted_facts",
            side_effect=Exception("boom"),
        ),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == "hi there"


@pytest.mark.asyncio
async def test_send_message_first_completion_call_offers_calendar_tools(client):
    session = (await client.post("/chat/sessions", json={})).json()

    responses = {
        "http://lmstudio.test/v1/chat/completions": [_ok_response("hi there")],
    }
    fake_client = _SequentialFakeLMStudioClient(responses)

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    _, completion_json = next(
        c for c in fake_client.calls if c[0].endswith("/v1/chat/completions")
    )
    assert completion_json["tools"] == CALENDAR_TOOLS
    assert completion_json["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_send_message_executes_calendar_tool_call(client):
    """Jarvis actually manages the calendar: a model reply containing a
    create_appointment tool call results in a real appointment row, and a
    follow-up completion call (without tools, carrying the tool result)
    produces the final user-visible reply."""
    session = (await client.post("/chat/sessions", json={})).json()

    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
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
    responses = {
        "http://lmstudio.test/v1/chat/completions": [
            _tool_call_response(tool_calls),
            _ok_response("Booked your dentist appointment for Sep 1 at 3pm."),
        ],
    }
    fake_client = _SequentialFakeLMStudioClient(responses)

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages",
            json={"content": "book me a dentist appointment sep 1 3-3:30pm"},
        )

    assert response.status_code == 200
    assert (
        response.json()["assistant_message"]["content"]
        == "Booked your dentist appointment for Sep 1 at 3pm."
    )

    list_response = await client.get("/calendar/appointments")
    titles = [a["title"] for a in list_response.json()]
    assert "Dentist" in titles

    # First two completions calls are the tool-call round trip; a possible
    # third is the best-effort memory-extraction call that runs after
    # (unrelated to tool calling, and this fake client has no response
    # queued for it, so it fails harmlessly — see other memory tests).
    completion_calls = [c for c in fake_client.calls if c[0].endswith("/v1/chat/completions")]
    assert len(completion_calls) >= 2
    assert completion_calls[0][1]["tools"] == CALENDAR_TOOLS
    followup_payload = completion_calls[1][1]
    assert "tools" not in followup_payload
    tool_message = next(m for m in followup_payload["messages"] if m["role"] == "tool")
    result = json.loads(tool_message["content"])
    assert result["appointment"]["title"] == "Dentist"


@pytest.mark.asyncio
async def test_send_message_falls_back_when_tools_rejected(client):
    """Not every LM Studio model/version supports tool calling — if the
    first (tools-enabled) completion call fails outright, retry once
    without tools rather than failing the whole message send."""
    session = (await client.post("/chat/sessions", json={})).json()

    rejected = httpx.Response(
        400,
        text="tools not supported by this model",
        request=httpx.Request("POST", "http://lmstudio.test/v1/chat/completions"),
    )
    responses = {
        "http://lmstudio.test/v1/chat/completions": [rejected, _ok_response("plain reply")],
    }
    fake_client = _SequentialFakeLMStudioClient(responses)

    with (
        patch("app.routers.chat.httpx.AsyncClient", return_value=fake_client),
        patch("app.routers.chat.fetch_relevant_memories", return_value=[]),
        patch("app.routers.chat.fetch_relevant_chunks", return_value=[]),
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == "plain reply"

    # First two completions calls are the tools-rejected retry round trip; a
    # possible third is the best-effort memory-extraction call afterward.
    completion_calls = [c for c in fake_client.calls if c[0].endswith("/v1/chat/completions")]
    assert len(completion_calls) >= 2
    assert completion_calls[0][1]["tools"] == CALENDAR_TOOLS
    assert "tools" not in completion_calls[1][1]
