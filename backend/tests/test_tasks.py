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


@pytest.mark.asyncio
async def test_delete_task(client):
    create_response = await client.post("/tasks", json={"title": "Delete me"})
    task_id = create_response.json()["id"]

    response = await client.delete(f"/tasks/{task_id}")
    assert response.status_code == 204

    list_response = await client.get("/tasks")
    titles = [t["title"] for t in list_response.json()]
    assert "Delete me" not in titles


@pytest.mark.asyncio
async def test_delete_task_not_found(client):
    response = await client.delete("/tasks/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "task not found"


@pytest.mark.asyncio
async def test_update_task(client):
    create_response = await client.post("/tasks", json={"title": "Original title"})
    task_id = create_response.json()["id"]

    response = await client.put(f"/tasks/{task_id}", json={"title": "Updated title"})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Updated title"
    assert body["description"] is None
    assert body["done"] is False

    list_response = await client.get("/tasks")
    assert list_response.json()[0]["title"] == "Updated title"


@pytest.mark.asyncio
async def test_update_task_partial(client):
    create_response = await client.post(
        "/tasks",
        json={"title": "Full task", "description": "Some desc", "due_date": "2026-12-31"},
    )
    task_id = create_response.json()["id"]

    response = await client.put(f"/tasks/{task_id}", json={"title": "Changed title"})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Changed title"
    assert body["description"] == "Some desc"      # unchanged
    assert body["due_date"] == "2026-12-31"          # unchanged


@pytest.mark.asyncio
async def test_update_task_not_found(client):
    response = await client.put("/tasks/999999", json={"title": "Ghost"})
    assert response.status_code == 404
    assert response.json()["detail"] == "task not found"
