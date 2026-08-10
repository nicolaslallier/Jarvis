import pytest


@pytest.mark.asyncio
async def test_create_contact(client):
    response = await client.post(
        "/contacts",
        json={"name": "Alice", "date": "2026-09-01", "date_type": "birthday"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Alice"
    assert body["date"] == "2026-09-01"
    assert body["date_type"] == "birthday"
    assert body["recurring_yearly"] is True
    assert body["reminder_lead_days"] == 7
    assert "id" in body
    assert "created_at" in body

    response = await client.post(
        "/contacts",
        json={
            "name": "Bob",
            "date": "2026-10-15",
            "date_type": "renewal",
            "recurring_yearly": False,
            "reminder_lead_days": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["date_type"] == "renewal"
    assert body["recurring_yearly"] is False
    assert body["reminder_lead_days"] == 3


@pytest.mark.asyncio
async def test_list_contacts_ordered_by_name(client):
    await client.post(
        "/contacts", json={"name": "Zoe", "date": "2026-09-01", "date_type": "birthday"}
    )
    await client.post(
        "/contacts", json={"name": "Amy", "date": "2026-09-01", "date_type": "birthday"}
    )

    response = await client.get("/contacts")
    assert response.status_code == 200
    body = response.json()
    assert [c["name"] for c in body] == ["Amy", "Zoe"]


@pytest.mark.asyncio
async def test_update_contact_partial(client):
    create_response = await client.post(
        "/contacts",
        json={
            "name": "Original",
            "date": "2026-09-01",
            "date_type": "birthday",
            "reminder_lead_days": 7,
        },
    )
    contact_id = create_response.json()["id"]

    response = await client.put(f"/contacts/{contact_id}", json={"name": "Updated"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Updated"
    assert body["date"] == "2026-09-01"  # unchanged
    assert body["reminder_lead_days"] == 7  # unchanged


@pytest.mark.asyncio
async def test_update_contact_not_found(client):
    response = await client.put("/contacts/999999", json={"name": "Ghost"})
    assert response.status_code == 404
    assert response.json()["detail"] == "contact not found"


@pytest.mark.asyncio
async def test_delete_contact(client):
    create_response = await client.post(
        "/contacts", json={"name": "Delete me", "date": "2026-09-01", "date_type": "birthday"}
    )
    contact_id = create_response.json()["id"]

    response = await client.delete(f"/contacts/{contact_id}")
    assert response.status_code == 204

    list_response = await client.get("/contacts")
    assert list_response.json() == []


@pytest.mark.asyncio
async def test_delete_contact_not_found(client):
    response = await client.delete("/contacts/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "contact not found"
