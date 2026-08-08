import pytest


@pytest.mark.asyncio
async def test_create_task(client):
    response = await client.post("/tasks", json={"title": "Buy milk"})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Buy milk"
    assert body["description"] is None
    assert body["due_date"] is None
    assert body["done"] is False
    assert "id" in body
    assert "created_at" in body

    response = await client.post(
        "/tasks",
        json={"title": "Renew passport", "description": "Bring photos", "due_date": "2026-09-01"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renew passport"
    assert body["description"] == "Bring photos"
    assert body["due_date"] == "2026-09-01"


@pytest.mark.asyncio
async def test_list_tasks(client):
    await client.post("/tasks", json={"title": "First"})
    await client.post("/tasks", json={"title": "Second"})

    response = await client.get("/tasks")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert [t["title"] for t in body] == ["First", "Second"]


@pytest.mark.asyncio
async def test_complete_task(client):
    create_response = await client.post("/tasks", json={"title": "Wash car"})
    task_id = create_response.json()["id"]

    response = await client.post(f"/tasks/{task_id}/complete")
    assert response.status_code == 200
    assert response.json()["done"] is True

    list_response = await client.get("/tasks")
    assert list_response.json()[0]["done"] is True


@pytest.mark.asyncio
async def test_complete_task_not_found(client):
    response = await client.post("/tasks/999999/complete")
    assert response.status_code == 404
    assert response.json()["detail"] == "task not found"
