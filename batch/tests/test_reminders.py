from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest
from jarvis_shared.db import Base
from jarvis_shared.models import Appointment, Task

from app.db import async_session, engine
from app.health_state import state
from app.jobs import reminders
from app.notifier import send_ntfy

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
def _reset_dedup_state():
    # reminders._last_notified is module-level, in-memory dedup state (see
    # its docstring) — clear it between tests so one test's notifications
    # don't suppress another's.
    reminders._last_notified.clear()
    yield
    reminders._last_notified.clear()


@pytest.fixture(autouse=True)
def _fake_settings():
    with patch("app.jobs.reminders.get_settings", return_value=_FakeSettings()):
        yield


async def _add_task(title: str, due_at: datetime | None, status: str = "todo") -> None:
    async with async_session() as session:
        session.add(Task(title=title, due_at=due_at, status=status))
        await session.commit()


async def _add_appointment(title: str, start_time: datetime) -> None:
    async with async_session() as session:
        session.add(
            Appointment(
                title=title,
                start_time=start_time,
                end_time=start_time + timedelta(hours=1),
            )
        )
        await session.commit()


def _canned_ntfy_response() -> httpx.Response:
    return httpx.Response(200, request=httpx.Request("POST", "https://ntfy.test/jarvis-test-topic"))


@pytest.mark.asyncio
async def test_no_overdue_tasks_or_appointments_skips_notification(db):
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await reminders.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_overdue_task_triggers_notification_with_expected_payload(db):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    await _add_task("Payer la facture", due_at=past, status="todo")

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await reminders.run()

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://ntfy.test/jarvis-test-topic"
    assert kwargs["headers"]["Title"] == "Rappel Jarvis"
    assert "Payer la facture" in kwargs["content"].decode("utf-8")
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_future_task_is_not_overdue(db):
    future = datetime.now(timezone.utc) + timedelta(days=1)
    await _add_task("Pas encore due", due_at=future, status="todo")

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await reminders.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_done_task_past_due_at_is_not_overdue(db):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    await _add_task("Deja fait", due_at=past, status="done")

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await reminders.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_appointment_just_after_local_midnight_tomorrow_counts(db):
    now_local = datetime.now(_TZ)
    tomorrow_start = datetime.combine(
        (now_local + timedelta(days=1)).date(), datetime.min.time(), tzinfo=_TZ
    )
    just_after_midnight = tomorrow_start + timedelta(minutes=1)
    await _add_appointment("Reveil matinal", just_after_midnight)

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await reminders.run()

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert "Reveil matinal" in kwargs["content"].decode("utf-8")
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_appointment_just_before_local_midnight_tomorrow_does_not_count(db):
    now_local = datetime.now(_TZ)
    tomorrow_start = datetime.combine(
        (now_local + timedelta(days=1)).date(), datetime.min.time(), tzinfo=_TZ
    )
    just_before_midnight = tomorrow_start - timedelta(minutes=1)
    await _add_appointment("Encore aujourd'hui", just_before_midnight)

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await reminders.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_appointment_two_days_out_does_not_count_as_tomorrow(db):
    now_local = datetime.now(_TZ)
    day_after_tomorrow = datetime.combine(
        (now_local + timedelta(days=2)).date(), datetime.min.time(), tzinfo=_TZ
    ) + timedelta(hours=9)
    await _add_appointment("Trop loin", day_after_tomorrow)

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await reminders.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_same_item_not_renotified_within_same_local_day(db):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    await _add_task("Rappel unique", due_at=past, status="todo")

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await reminders.run()
        await reminders.run()

    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_ntfy_no_op_when_topic_empty():
    with patch("app.jobs.reminders.get_settings", return_value=_FakeSettings(ntfy_topic="")):
        with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
            await send_ntfy(_FakeSettings(ntfy_topic=""), title="Rappel Jarvis", message="test")

    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_send_ntfy_posts_expected_url_and_headers():
    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await send_ntfy(_FakeSettings(), title="Rappel Jarvis", message="ligne 1\nligne 2")

    args, kwargs = mock_post.call_args
    assert args[0] == "https://ntfy.test/jarvis-test-topic"
    assert kwargs["headers"]["Title"] == "Rappel Jarvis"
    assert kwargs["content"] == "ligne 1\nligne 2".encode("utf-8")
