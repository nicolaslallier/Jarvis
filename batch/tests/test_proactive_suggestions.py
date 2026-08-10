from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest
from jarvis_shared.db import Base
from jarvis_shared.models import Appointment, Task
from sqlalchemy import select, text

from app.db import async_session, engine
from app.health_state import state
from app.jobs import proactive_suggestions

_TZ = ZoneInfo("America/Toronto")


@dataclass
class _FakeSettings:
    ntfy_url: str = "https://ntfy.test"
    ntfy_topic: str = "jarvis-test-topic"
    timezone: str = "America/Toronto"


@pytest.fixture
async def db():
    await engine.dispose()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def _fake_settings():
    with patch("app.jobs.proactive_suggestions.get_settings", return_value=_FakeSettings()):
        yield


async def _add_appointment(title: str, start_time: datetime, end_time: datetime) -> Appointment:
    async with async_session() as session:
        appt = Appointment(title=title, start_time=start_time, end_time=end_time)
        session.add(appt)
        await session.commit()
        await session.refresh(appt)
        return appt


async def _add_task(title: str, created_at: datetime, status: str = "todo") -> Task:
    async with async_session() as session:
        task = Task(title=title, status=status)
        session.add(task)
        await session.commit()
        await session.refresh(task)
        # created_at has a server_default, so it must be overwritten after
        # the initial insert to backdate it for the staleness check.
        await session.execute(
            text("UPDATE tasks SET created_at = :created_at WHERE id = :id"),
            {"created_at": created_at, "id": task.id},
        )
        await session.commit()
        await session.refresh(task)
        return task


def _canned_ntfy_response() -> httpx.Response:
    return httpx.Response(200, request=httpx.Request("POST", "https://ntfy.test/jarvis-test-topic"))


@pytest.mark.asyncio
async def test_no_conflicts_or_stale_tasks_skips_notification(db):
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await proactive_suggestions.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_overlapping_appointments_trigger_one_conflict_alert(db):
    now_local = datetime.now(_TZ)
    start = now_local + timedelta(days=1)
    await _add_appointment("Dentiste", start, start + timedelta(hours=1))
    await _add_appointment("Reunion", start + timedelta(minutes=30), start + timedelta(hours=2))

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await proactive_suggestions.run()

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    body = kwargs["content"].decode("utf-8")
    assert "Dentiste" in body
    assert "Reunion" in body
    assert kwargs["headers"]["Title"] == "Conflit d'horaire"
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_non_overlapping_appointments_do_not_trigger_alert(db):
    now_local = datetime.now(_TZ)
    start = now_local + timedelta(days=1)
    await _add_appointment("Matin", start, start + timedelta(hours=1))
    await _add_appointment("Apres-midi", start + timedelta(hours=2), start + timedelta(hours=3))

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await proactive_suggestions.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_conflict_outside_window_does_not_trigger_alert(db):
    now_local = datetime.now(_TZ)
    start = now_local + timedelta(days=30)
    await _add_appointment("Loin 1", start, start + timedelta(hours=1))
    await _add_appointment("Loin 2", start + timedelta(minutes=30), start + timedelta(hours=2))

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await proactive_suggestions.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_conflicting_pair_not_renotified_same_day(db):
    now_local = datetime.now(_TZ)
    start = now_local + timedelta(days=1)
    await _add_appointment("A", start, start + timedelta(hours=1))
    await _add_appointment("B", start + timedelta(minutes=30), start + timedelta(hours=2))

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await proactive_suggestions.run()
        await proactive_suggestions.run()

    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_stale_task_triggers_nudge(db):
    old = datetime.now(timezone.utc) - timedelta(days=30)
    await _add_task("Vieille tache", created_at=old, status="todo")

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await proactive_suggestions.run()

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert "Vieille tache" in kwargs["content"].decode("utf-8")
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_recently_updated_task_does_not_trigger_nudge(db):
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    await _add_task("Tache recente", created_at=recent, status="todo")

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await proactive_suggestions.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_done_stale_task_is_excluded(db):
    old = datetime.now(timezone.utc) - timedelta(days=30)
    await _add_task("Tache terminee", created_at=old, status="done")

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await proactive_suggestions.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_multiple_stale_tasks_batched_into_one_message(db):
    old = datetime.now(timezone.utc) - timedelta(days=30)
    await _add_task("Tache 1", created_at=old, status="todo")
    await _add_task("Tache 2", created_at=old, status="doing")

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await proactive_suggestions.run()

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    body = kwargs["content"].decode("utf-8")
    assert "Tache 1" in body
    assert "Tache 2" in body


@pytest.mark.asyncio
async def test_stale_task_not_renotified_within_same_week(db):
    old = datetime.now(timezone.utc) - timedelta(days=30)
    await _add_task("Tache stable", created_at=old, status="todo")

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await proactive_suggestions.run()
        await proactive_suggestions.run()

    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_stale_task_dedup_persists_across_a_fresh_session_simulating_restart(db):
    old = datetime.now(timezone.utc) - timedelta(days=30)
    task = await _add_task("Tache apres redemarrage", created_at=old, status="todo")

    today = datetime.now(_TZ).date()
    week_start = today - timedelta(days=today.weekday())
    async with async_session() as session:
        await session.execute(
            text(
                "INSERT INTO notifications_sent (kind, entity_id, notified_date) "
                "VALUES (:kind, :entity_id, :notified_date)"
            ),
            {"kind": "stale_task", "entity_id": task.id, "notified_date": week_start},
        )
        await session.commit()

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await proactive_suggestions.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_conflict_dedup_persists_across_a_fresh_session_simulating_restart(db):
    now_local = datetime.now(_TZ)
    start = now_local + timedelta(days=1)
    a = await _add_appointment("A", start, start + timedelta(hours=1))
    b = await _add_appointment("B", start + timedelta(minutes=30), start + timedelta(hours=2))
    low, high = (a, b) if a.id < b.id else (b, a)
    pair_id = low.id * 100_000 + high.id

    today = datetime.now(_TZ).date()
    async with async_session() as session:
        await session.execute(
            text(
                "INSERT INTO notifications_sent (kind, entity_id, notified_date) "
                "VALUES (:kind, :entity_id, :notified_date)"
            ),
            {"kind": "calendar_conflict", "entity_id": pair_id, "notified_date": today},
        )
        await session.commit()

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await proactive_suggestions.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_both_conflict_and_stale_task_fire_together(db):
    now_local = datetime.now(_TZ)
    start = now_local + timedelta(days=1)
    await _add_appointment("A", start, start + timedelta(hours=1))
    await _add_appointment("B", start + timedelta(minutes=30), start + timedelta(hours=2))
    old = datetime.now(timezone.utc) - timedelta(days=30)
    await _add_task("Vieille tache", created_at=old, status="todo")

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await proactive_suggestions.run()

    assert mock_post.call_count == 2
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_task_query_uses_the_expected_columns(db):
    """Sanity check that Task rows round-trip through the session as
    expected, guarding against a future schema change silently breaking the
    staleness query this job relies on."""
    old = datetime.now(timezone.utc) - timedelta(days=30)
    await _add_task("Une tache", created_at=old, status="todo")

    async with async_session() as session:
        result = await session.execute(select(Task))
        task = result.scalars().one()

    assert task.status == "todo"
    assert task.created_at < datetime.now(timezone.utc) - timedelta(days=20)
