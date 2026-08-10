import pytest


@pytest.mark.asyncio
async def test_create_appointment(client):
    response = await client.post(
        "/calendar/appointments",
        json={
            "title": "Dentist",
            "start_time": "2026-09-01T15:00:00+00:00",
            "end_time": "2026-09-01T15:30:00+00:00",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Dentist"
    assert body["description"] is None
    assert body["location"] is None
    assert body["all_day"] is False
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body

    response = await client.post(
        "/calendar/appointments",
        json={
            "title": "Trip",
            "start_time": "2026-09-05T00:00:00+00:00",
            "end_time": "2026-09-06T00:00:00+00:00",
            "description": "Weekend away",
            "location": "Mont-Tremblant",
            "all_day": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Weekend away"
    assert body["location"] == "Mont-Tremblant"
    assert body["all_day"] is True


@pytest.mark.asyncio
async def test_list_appointments_ordered_by_start_time(client):
    await client.post(
        "/calendar/appointments",
        json={
            "title": "Later",
            "start_time": "2026-09-10T10:00:00+00:00",
            "end_time": "2026-09-10T11:00:00+00:00",
        },
    )
    await client.post(
        "/calendar/appointments",
        json={
            "title": "Earlier",
            "start_time": "2026-09-01T10:00:00+00:00",
            "end_time": "2026-09-01T11:00:00+00:00",
        },
    )

    response = await client.get("/calendar/appointments")
    assert response.status_code == 200
    body = response.json()
    assert [a["title"] for a in body] == ["Earlier", "Later"]


@pytest.mark.asyncio
async def test_get_appointment(client):
    create_response = await client.post(
        "/calendar/appointments",
        json={
            "title": "Checkup",
            "start_time": "2026-09-01T10:00:00+00:00",
            "end_time": "2026-09-01T11:00:00+00:00",
        },
    )
    appointment_id = create_response.json()["id"]

    response = await client.get(f"/calendar/appointments/{appointment_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Checkup"


@pytest.mark.asyncio
async def test_get_appointment_not_found(client):
    response = await client.get("/calendar/appointments/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "appointment not found"


@pytest.mark.asyncio
async def test_update_appointment_partial(client):
    create_response = await client.post(
        "/calendar/appointments",
        json={
            "title": "Original",
            "start_time": "2026-09-01T10:00:00+00:00",
            "end_time": "2026-09-01T11:00:00+00:00",
            "location": "Office",
        },
    )
    appointment_id = create_response.json()["id"]

    response = await client.put(
        f"/calendar/appointments/{appointment_id}", json={"title": "Updated"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Updated"
    assert body["location"] == "Office"  # unchanged


@pytest.mark.asyncio
async def test_appointment_pending_review_default_and_filter(client):
    confirmed = await client.post(
        "/calendar/appointments",
        json={
            "title": "Manual",
            "start_time": "2026-09-01T10:00:00+00:00",
            "end_time": "2026-09-01T11:00:00+00:00",
        },
    )
    assert confirmed.json()["pending_review"] is False

    # Nothing creates draft appointments through this endpoint (that's
    # email_ingest's job, via direct ORM inserts in batch/), so exercise the
    # filter with a manually-flipped row instead of a dedicated create path.
    draft = await client.post(
        "/calendar/appointments",
        json={
            "title": "Draft",
            "start_time": "2026-09-02T10:00:00+00:00",
            "end_time": "2026-09-02T11:00:00+00:00",
        },
    )
    draft_id = draft.json()["id"]
    await client.put(f"/calendar/appointments/{draft_id}", json={"pending_review": True})

    response = await client.get("/calendar/appointments", params={"pending_review": "true"})
    assert response.status_code == 200
    body = response.json()
    assert [a["id"] for a in body] == [draft_id]

    response = await client.get("/calendar/appointments", params={"pending_review": "false"})
    assert [a["id"] for a in response.json()] == [confirmed.json()["id"]]


@pytest.mark.asyncio
async def test_confirm_pending_review_appointment(client):
    create_response = await client.post(
        "/calendar/appointments",
        json={
            "title": "Draft",
            "start_time": "2026-09-01T10:00:00+00:00",
            "end_time": "2026-09-01T11:00:00+00:00",
        },
    )
    appointment_id = create_response.json()["id"]
    await client.put(f"/calendar/appointments/{appointment_id}", json={"pending_review": True})

    response = await client.put(
        f"/calendar/appointments/{appointment_id}", json={"pending_review": False}
    )
    assert response.status_code == 200
    assert response.json()["pending_review"] is False


@pytest.mark.asyncio
async def test_update_appointment_not_found(client):
    response = await client.put("/calendar/appointments/999999", json={"title": "Ghost"})
    assert response.status_code == 404
    assert response.json()["detail"] == "appointment not found"


@pytest.mark.asyncio
async def test_delete_appointment(client):
    create_response = await client.post(
        "/calendar/appointments",
        json={
            "title": "Delete me",
            "start_time": "2026-09-01T10:00:00+00:00",
            "end_time": "2026-09-01T11:00:00+00:00",
        },
    )
    appointment_id = create_response.json()["id"]

    response = await client.delete(f"/calendar/appointments/{appointment_id}")
    assert response.status_code == 204

    list_response = await client.get("/calendar/appointments")
    assert list_response.json() == []


@pytest.mark.asyncio
async def test_delete_appointment_not_found(client):
    response = await client.delete("/calendar/appointments/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "appointment not found"
