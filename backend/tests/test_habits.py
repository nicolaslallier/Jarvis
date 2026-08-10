from datetime import UTC, datetime, timedelta

import pytest

from app.db import async_session
from app.models import Habit


async def _backdate_last_completed(habit_id: int, delta: timedelta) -> None:
    """Directly rewrite a habit's last_completed_at so complete_habit sees a
    realistic gap, instead of the sub-millisecond gap two back-to-back
    /complete calls would otherwise produce in a fast test run."""
    async with async_session() as session:
        habit = await session.get(Habit, habit_id)
        habit.last_completed_at = datetime.now(UTC) - delta
        await session.commit()


@pytest.mark.asyncio
async def test_create_habit(client):
    response = await client.post("/habits", json={"name": "Méditer", "frequency": "daily"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Méditer"
    assert body["frequency"] == "daily"
    assert body["streak_count"] == 0
    assert body["last_completed_at"] is None
    assert "id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_list_habits(client):
    await client.post("/habits", json={"name": "Courir", "frequency": "daily"})
    await client.post("/habits", json={"name": "Lire", "frequency": "weekly"})

    response = await client.get("/habits")
    assert response.status_code == 200
    names = [h["name"] for h in response.json()]
    assert names == ["Courir", "Lire"]


@pytest.mark.asyncio
async def test_complete_habit_first_time_sets_streak_to_one(client):
    create_response = await client.post("/habits", json={"name": "Boire de l'eau", "frequency": "daily"})
    habit_id = create_response.json()["id"]

    response = await client.post(f"/habits/{habit_id}/complete")
    assert response.status_code == 200
    body = response.json()
    assert body["streak_count"] == 1
    assert body["last_completed_at"] is not None


@pytest.mark.asyncio
async def test_complete_habit_within_window_increments_streak(client):
    create_response = await client.post("/habits", json={"name": "Étirements", "frequency": "daily"})
    habit_id = create_response.json()["id"]
    await client.post(f"/habits/{habit_id}/complete")

    # Just under the daily grace window (2 days) — should still count as
    # consecutive and bump the streak.
    await _backdate_last_completed(habit_id, timedelta(hours=30))

    response = await client.post(f"/habits/{habit_id}/complete")
    assert response.status_code == 200
    body = response.json()
    assert body["streak_count"] == 2


@pytest.mark.asyncio
async def test_complete_habit_weekly_within_window_increments_streak(client):
    create_response = await client.post("/habits", json={"name": "Grand ménage", "frequency": "weekly"})
    habit_id = create_response.json()["id"]
    await client.post(f"/habits/{habit_id}/complete")

    # Just under the weekly grace window (9 days).
    await _backdate_last_completed(habit_id, timedelta(days=8))

    response = await client.post(f"/habits/{habit_id}/complete")
    assert response.status_code == 200
    assert response.json()["streak_count"] == 2


@pytest.mark.asyncio
async def test_complete_habit_after_gap_resets_streak(client):
    create_response = await client.post("/habits", json={"name": "Yoga", "frequency": "daily"})
    habit_id = create_response.json()["id"]
    await client.post(f"/habits/{habit_id}/complete")

    # Well beyond the daily grace window — the streak should reset, not
    # accumulate.
    await _backdate_last_completed(habit_id, timedelta(days=5))

    response = await client.post(f"/habits/{habit_id}/complete")
    assert response.status_code == 200
    body = response.json()
    assert body["streak_count"] == 1


@pytest.mark.asyncio
async def test_complete_habit_not_found(client):
    response = await client.post("/habits/999999/complete")
    assert response.status_code == 404
    assert response.json()["detail"] == "habit not found"


@pytest.mark.asyncio
async def test_delete_habit(client):
    create_response = await client.post("/habits", json={"name": "Journal", "frequency": "daily"})
    habit_id = create_response.json()["id"]

    response = await client.delete(f"/habits/{habit_id}")
    assert response.status_code == 204

    list_response = await client.get("/habits")
    names = [h["name"] for h in list_response.json()]
    assert "Journal" not in names


@pytest.mark.asyncio
async def test_delete_habit_not_found(client):
    response = await client.delete("/habits/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "habit not found"
