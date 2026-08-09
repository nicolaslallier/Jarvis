from unittest.mock import patch

import httpx
import pytest

from app.rag import RetrievedChunk


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

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, *args, **kwargs):
        self.last_json = kwargs.get("json")
        if self._error is not None:
            raise self._error
        return self._response


def _ok_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
        request=httpx.Request("POST", "http://lmstudio.test/v1/chat/completions"),
    )


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

    sent_messages = fake_client2.last_json["messages"]
    assert [m["content"] for m in sent_messages] == ["one", "first reply", "two"]


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
    assert sent_messages[0]["role"] == "system"
    assert "Paris is the capital of France." in sent_messages[0]["content"]
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
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    _, completion_json = next(c for c in fake_client.calls if c[0].endswith("/v1/chat/completions"))
    assert completion_json["messages"] == [{"role": "user", "content": "hello"}]


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
    ):
        response = await client.post(
            f"/chat/sessions/{session['id']}/messages", json={"content": "hello"}
        )

    assert response.status_code == 200
    assert response.json()["assistant_message"]["content"] == "still works"
    _, completion_json = next(c for c in fake_client.calls if c[0].endswith("/v1/chat/completions"))
    assert completion_json["messages"] == [{"role": "user", "content": "hello"}]
