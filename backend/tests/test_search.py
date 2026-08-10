from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_search_matches_task_by_title(client):
    await client.post("/tasks", json={"title": "Buy birthday cake for Sam"})
    await client.post("/tasks", json={"title": "Unrelated errand"})

    with patch("app.search_service.embed_text", return_value=None):
        response = await client.get("/search", params={"q": "birthday cake"})

    assert response.status_code == 200
    body = response.json()
    task_results = [r for r in body["results"] if r["kind"] == "task"]
    assert len(task_results) == 1
    assert task_results[0]["title"] == "Buy birthday cake for Sam"
    assert task_results[0]["score"] is None


@pytest.mark.asyncio
async def test_search_matches_task_by_description(client):
    await client.post(
        "/tasks", json={"title": "Groceries", "description": "Need to buy a birthday cake for Sam"}
    )

    with patch("app.search_service.embed_text", return_value=None):
        response = await client.get("/search", params={"q": "birthday cake"})

    assert response.status_code == 200
    task_results = [r for r in response.json()["results"] if r["kind"] == "task"]
    assert len(task_results) == 1
    assert task_results[0]["title"] == "Groceries"
    assert "birthday cake" in task_results[0]["snippet"]


@pytest.mark.asyncio
async def test_search_still_returns_ilike_results_when_embedding_fails(client):
    """The embedding call backs the file_chunk/memory legs only — if LM
    Studio is unreachable (or the call otherwise fails), the ILIKE-based
    legs (tasks/appointments/chat_messages) must still come back rather
    than the whole request failing."""
    await client.post("/tasks", json={"title": "Renew passport before trip"})

    with patch("app.search_service.embed_text", side_effect=Exception("LM Studio unreachable")):
        response = await client.get("/search", params={"q": "passport"})

    assert response.status_code == 200
    body = response.json()
    assert any(r["kind"] == "task" and r["title"] == "Renew passport before trip" for r in body["results"])
    # No embedding was produced, so neither vector-based kind should appear.
    assert not any(r["kind"] in ("file_chunk", "memory") for r in body["results"])


@pytest.mark.asyncio
async def test_search_returns_empty_results_when_embedding_returns_none_and_no_ilike_matches(client):
    with patch("app.search_service.embed_text", return_value=None):
        response = await client.get("/search", params={"q": "nothing matches this at all"})

    assert response.status_code == 200
    assert response.json() == {"query": "nothing matches this at all", "results": []}


@pytest.mark.asyncio
async def test_search_response_shape(client):
    await client.post("/tasks", json={"title": "Call the dentist"})

    with patch("app.search_service.embed_text", return_value=None):
        response = await client.get("/search", params={"q": "dentist"})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"query", "results"}
    assert body["query"] == "dentist"
    assert isinstance(body["results"], list)
    assert len(body["results"]) >= 1
    for result in body["results"]:
        assert set(result.keys()) == {"kind", "id", "title", "snippet", "score"}
        assert result["kind"] in ("task", "appointment", "file_chunk", "memory", "chat_message")
        assert isinstance(result["id"], int)
        assert isinstance(result["title"], str)
        assert isinstance(result["snippet"], str)
        assert result["score"] is None or isinstance(result["score"], float)


@pytest.mark.asyncio
async def test_search_missing_query_returns_422(client):
    response = await client.get("/search")
    assert response.status_code == 422
