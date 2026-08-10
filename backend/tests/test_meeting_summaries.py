from unittest.mock import patch

import pytest

FAKE_EMBEDDING = [0.1, 0.2, 0.3]


def _patch_embed(**kwargs):
    return patch("app.routers.meeting_summaries.embed_text", **kwargs)


@pytest.mark.asyncio
async def test_create_meeting_summary(client):
    with _patch_embed(return_value=FAKE_EMBEDDING):
        response = await client.post(
            "/meeting-summaries",
            json={
                "title": "Point hebdomadaire",
                "meeting_date": "2026-08-10T09:00:00Z",
                "content": "Discussion du budget Q3.",
                "participants": "Alice, Bob",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Point hebdomadaire"
    assert body["content"] == "Discussion du budget Q3."
    assert body["participants"] == "Alice, Bob"
    assert body["appointment_id"] is None
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_create_meeting_summary_embedding_failure_returns_502(client):
    with _patch_embed(return_value=None):
        response = await client.post(
            "/meeting-summaries",
            json={
                "title": "Point hebdomadaire",
                "meeting_date": "2026-08-10T09:00:00Z",
                "content": "Discussion du budget Q3.",
            },
        )

    assert response.status_code == 502

    with _patch_embed(return_value=FAKE_EMBEDDING):
        listed = await client.get("/meeting-summaries")
    assert listed.json() == []


@pytest.mark.asyncio
async def test_list_meeting_summaries_ordered_by_meeting_date_desc(client):
    with _patch_embed(return_value=FAKE_EMBEDDING):
        await client.post(
            "/meeting-summaries",
            json={"title": "Ancien", "meeting_date": "2026-08-01T09:00:00Z", "content": "..."},
        )
        await client.post(
            "/meeting-summaries",
            json={"title": "Recent", "meeting_date": "2026-08-09T09:00:00Z", "content": "..."},
        )

    response = await client.get("/meeting-summaries")
    assert response.status_code == 200
    body = response.json()
    assert [m["title"] for m in body] == ["Recent", "Ancien"]


@pytest.mark.asyncio
async def test_get_meeting_summary_not_found(client):
    response = await client.get("/meeting-summaries/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "meeting summary not found"


@pytest.mark.asyncio
async def test_update_meeting_summary_partial(client):
    with _patch_embed(return_value=FAKE_EMBEDDING):
        create_response = await client.post(
            "/meeting-summaries",
            json={
                "title": "Original",
                "meeting_date": "2026-08-10T09:00:00Z",
                "content": "Contenu original.",
                "participants": "Alice",
            },
        )
        summary_id = create_response.json()["id"]

        response = await client.put(f"/meeting-summaries/{summary_id}", json={"title": "Modifie"})

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Modifie"
    assert body["content"] == "Contenu original."  # unchanged
    assert body["participants"] == "Alice"  # unchanged


@pytest.mark.asyncio
async def test_update_meeting_summary_not_found(client):
    with _patch_embed(return_value=FAKE_EMBEDDING):
        response = await client.put("/meeting-summaries/999999", json={"title": "Fantome"})
    assert response.status_code == 404
    assert response.json()["detail"] == "meeting summary not found"


@pytest.mark.asyncio
async def test_update_meeting_summary_embedding_failure_returns_502(client):
    with _patch_embed(return_value=FAKE_EMBEDDING):
        create_response = await client.post(
            "/meeting-summaries",
            json={"title": "Original", "meeting_date": "2026-08-10T09:00:00Z", "content": "..."},
        )
        summary_id = create_response.json()["id"]

    with _patch_embed(return_value=None):
        response = await client.put(f"/meeting-summaries/{summary_id}", json={"title": "Corrompu"})

    assert response.status_code == 502

    with _patch_embed(return_value=FAKE_EMBEDDING):
        listed = await client.get(f"/meeting-summaries/{summary_id}")
    assert listed.json()["title"] == "Original"


@pytest.mark.asyncio
async def test_delete_meeting_summary(client):
    with _patch_embed(return_value=FAKE_EMBEDDING):
        create_response = await client.post(
            "/meeting-summaries",
            json={"title": "A supprimer", "meeting_date": "2026-08-10T09:00:00Z", "content": "..."},
        )
        summary_id = create_response.json()["id"]

    response = await client.delete(f"/meeting-summaries/{summary_id}")
    assert response.status_code == 204

    list_response = await client.get("/meeting-summaries")
    assert list_response.json() == []


@pytest.mark.asyncio
async def test_delete_meeting_summary_not_found(client):
    response = await client.delete("/meeting-summaries/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "meeting summary not found"
