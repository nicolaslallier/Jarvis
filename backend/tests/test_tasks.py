import pytest


@pytest.mark.asyncio
async def test_create_task(client):
    response = await client.post("/tasks", json={"title": "Buy milk"})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Buy milk"
    assert body["description"] is None
    assert body["due_at"] is None
    assert body["status"] == "todo"
    assert body["priority"] == "normal"
    assert body["completed_at"] is None
    assert "id" in body
    assert "created_at" in body

    response = await client.post(
        "/tasks",
        json={
            "title": "Renew passport",
            "description": "Bring photos",
            "due_at": "2026-09-01T12:00:00Z",
            "priority": "high",
            "project": "Admin",
            "tags": ["important", "government"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renew passport"
    assert body["description"] == "Bring photos"
    assert body["due_at"] == "2026-09-01T12:00:00"
    assert body["priority"] == "high"
    assert body["project"] == "Admin"
    assert body["tags"] == ["important", "government"]


@pytest.mark.asyncio
async def test_list_tasks_sorted_open_before_done(client):
    first = await client.post("/tasks", json={"title": "First", "due_at": "2026-09-05T00:00:00Z"})
    second = await client.post("/tasks", json={"title": "Second", "due_at": "2026-09-01T00:00:00Z"})
    third = await client.post("/tasks", json={"title": "Third"})
    await client.put(f"/tasks/{third.json()['id']}", json={"status": "done"})

    response = await client.get("/tasks")
    assert response.status_code == 200
    titles = [t["title"] for t in response.json()]
    # "Second" is due earlier than "First", undated tasks sort after dated
    # ones within the open group, and done tasks trail at the end.
    assert titles == ["Second", "First", "Third"]
    assert first.json()["id"] and second.json()["id"]


@pytest.mark.asyncio
async def test_complete_task(client):
    create_response = await client.post("/tasks", json={"title": "Wash car"})
    task_id = create_response.json()["id"]

    response = await client.post(f"/tasks/{task_id}/complete")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert body["completed_at"] is not None

    list_response = await client.get("/tasks")
    assert list_response.json()[0]["status"] == "done"


@pytest.mark.asyncio
async def test_reopen_task(client):
    create_response = await client.post("/tasks", json={"title": "Wash car"})
    task_id = create_response.json()["id"]
    await client.post(f"/tasks/{task_id}/complete")

    response = await client.put(f"/tasks/{task_id}", json={"status": "todo"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "todo"
    assert body["completed_at"] is None


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
    assert body["status"] == "todo"

    list_response = await client.get("/tasks")
    assert list_response.json()[0]["title"] == "Updated title"


@pytest.mark.asyncio
async def test_update_task_partial(client):
    create_response = await client.post(
        "/tasks",
        json={"title": "Full task", "description": "Some desc", "due_at": "2026-12-31T00:00:00Z"},
    )
    task_id = create_response.json()["id"]

    response = await client.put(f"/tasks/{task_id}", json={"title": "Changed title"})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Changed title"
    assert body["description"] == "Some desc"          # unchanged
    assert body["due_at"] == "2026-12-31T00:00:00"      # unchanged


@pytest.mark.asyncio
async def test_update_task_clears_due_at_and_description(client):
    create_response = await client.post(
        "/tasks",
        json={"title": "Full task", "description": "Some desc", "due_at": "2026-12-31T00:00:00Z"},
    )
    task_id = create_response.json()["id"]

    # Explicit nulls must actually clear the fields, unlike simply omitting them.
    response = await client.put(
        f"/tasks/{task_id}", json={"description": None, "due_at": None}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] is None
    assert body["due_at"] is None
    assert body["title"] == "Full task"  # untouched field stays as-is


@pytest.mark.asyncio
async def test_update_task_not_found(client):
    response = await client.put("/tasks/999999", json={"title": "Ghost"})
    assert response.status_code == 404
    assert response.json()["detail"] == "task not found"


@pytest.mark.asyncio
async def test_task_count(client):
    a = await client.post("/tasks", json={"title": "A"})
    await client.post("/tasks", json={"title": "B"})
    await client.post(f"/tasks/{a.json()['id']}/complete")

    response = await client.get("/tasks/count")
    assert response.status_code == 200
    body = response.json()
    assert body == {"total": 2, "done": 1, "active": 1}


@pytest.mark.asyncio
async def test_subtask_parent_link(client):
    parent = await client.post("/tasks", json={"title": "Organize dinner"})
    parent_id = parent.json()["id"]
    child = await client.post(
        "/tasks", json={"title": "Buy corn", "parent_id": parent_id}
    )
    assert child.status_code == 200
    assert child.json()["parent_id"] == parent_id
