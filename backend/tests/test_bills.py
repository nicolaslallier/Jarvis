import pytest


@pytest.mark.asyncio
async def test_create_bill(client):
    response = await client.post(
        "/bills",
        json={"name": "Electricite", "amount": "125.50", "due_day": 15, "recurrence": "monthly"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Electricite"
    assert body["amount"] == "125.50"
    assert body["due_day"] == 15
    assert body["recurrence"] == "monthly"
    assert "id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_list_bills_ordered_by_due_day(client):
    await client.post(
        "/bills",
        json={"name": "Later", "amount": "10.00", "due_day": 28, "recurrence": "monthly"},
    )
    await client.post(
        "/bills",
        json={"name": "Earlier", "amount": "20.00", "due_day": 5, "recurrence": "monthly"},
    )

    response = await client.get("/bills")
    assert response.status_code == 200
    body = response.json()
    assert [b["name"] for b in body] == ["Earlier", "Later"]


@pytest.mark.asyncio
async def test_update_bill_partial(client):
    create_response = await client.post(
        "/bills",
        json={"name": "Original", "amount": "50.00", "due_day": 1, "recurrence": "monthly"},
    )
    bill_id = create_response.json()["id"]

    response = await client.put(f"/bills/{bill_id}", json={"name": "Updated"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Updated"
    assert body["amount"] == "50.00"  # unchanged
    assert body["due_day"] == 1  # unchanged


@pytest.mark.asyncio
async def test_update_bill_not_found(client):
    response = await client.put("/bills/999999", json={"name": "Ghost"})
    assert response.status_code == 404
    assert response.json()["detail"] == "bill not found"


@pytest.mark.asyncio
async def test_delete_bill(client):
    create_response = await client.post(
        "/bills",
        json={"name": "Delete me", "amount": "5.00", "due_day": 10, "recurrence": "yearly"},
    )
    bill_id = create_response.json()["id"]

    response = await client.delete(f"/bills/{bill_id}")
    assert response.status_code == 204

    list_response = await client.get("/bills")
    assert list_response.json() == []


@pytest.mark.asyncio
async def test_delete_bill_not_found(client):
    response = await client.delete("/bills/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "bill not found"
