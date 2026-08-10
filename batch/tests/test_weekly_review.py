from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest
from jarvis_shared.db import Base
from jarvis_shared.models import Task

from app.db import async_session, engine
from app.health_state import state
from app.jobs import weekly_review

_TZ = ZoneInfo("America/Toronto")

# 2026-08-09 is a Sunday (see CLAUDE.md's currentDate convention for this
# repo's "today"); 2026-08-10 is the following Monday. Fixed calendar dates
# rather than "whatever day the test happens to run on" so the Sunday-
# evening gate is exercised deterministically regardless of when the test
# suite executes.
_SUNDAY_EVENING = datetime(2026, 8, 9, 19, 0, tzinfo=_TZ)
_SUNDAY_AFTERNOON = datetime(2026, 8, 9, 15, 0, tzinfo=_TZ)
_MONDAY_EVENING = datetime(2026, 8, 10, 19, 0, tzinfo=_TZ)


def _frozen_datetime(frozen: datetime):
    """A datetime subclass whose `now()` always returns `frozen` (converted
    to the requested tz, if any). Passed via `patch(...)` in place of the
    real `datetime` class so weekly_review.run()'s `datetime.now(tz)` call
    is deterministic, since the Sunday-evening gate depends on which
    weekday/hour "now" actually is."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen

    return _Frozen


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
    with patch("app.jobs.weekly_review.get_settings", return_value=_FakeSettings()):
        yield


async def _add_task(
    title: str,
    status: str = "todo",
    due_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> None:
    async with async_session() as session:
        session.add(Task(title=title, status=status, due_at=due_at, completed_at=completed_at))
        await session.commit()


def _canned_ntfy_response() -> httpx.Response:
    return httpx.Response(200, request=httpx.Request("POST", "https://ntfy.test/jarvis-test-topic"))


def _run_at(frozen: datetime):
    return patch("app.jobs.weekly_review.datetime", _frozen_datetime(frozen))


@pytest.mark.asyncio
async def test_does_not_send_on_non_sunday_tick(db):
    with _run_at(_MONDAY_EVENING):
        with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
            await weekly_review.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_does_not_send_on_sunday_before_evening_hour(db):
    with _run_at(_SUNDAY_AFTERNOON):
        with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
            await weekly_review.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_sunday_evening_sends_summary_with_expected_counts(db):
    now_utc = _SUNDAY_EVENING.astimezone(ZoneInfo("UTC"))

    # Completed this week: counts.
    await _add_task(
        "Fait cette semaine",
        status="done",
        completed_at=now_utc - timedelta(days=2),
    )
    # Completed too long ago: excluded from the "this week" count.
    await _add_task(
        "Fait il y a longtemps",
        status="done",
        completed_at=now_utc - timedelta(days=10),
    )
    # Overdue: counts.
    await _add_task("En retard", status="todo", due_at=now_utc - timedelta(days=1))
    # Overdue but cancelled: excluded.
    await _add_task("Annulee et en retard", status="cancelled", due_at=now_utc - timedelta(days=1))
    # Due within the coming week: counts.
    await _add_task("A venir bientot", status="todo", due_at=now_utc + timedelta(days=3))
    # Due more than a week out: excluded.
    await _add_task("Trop loin", status="todo", due_at=now_utc + timedelta(days=20))

    with _run_at(_SUNDAY_EVENING):
        with patch(
            "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
        ) as mock_post:
            await weekly_review.run()

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    message = kwargs["content"].decode("utf-8")

    assert "Fait cette semaine" in message
    assert "Fait il y a longtemps" not in message
    assert "En retard" in message
    assert "Annulee et en retard" not in message
    assert "A venir bientot" in message
    assert "Trop loin" not in message

    assert "Tâches complétées cette semaine (1)" in message
    assert "Tâches en retard (1)" in message
    assert "Tâches à venir cette semaine (1)" in message
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_running_twice_on_the_same_sunday_only_sends_once(db):
    await _add_task("Rappel unique", status="todo", due_at=_SUNDAY_EVENING - timedelta(days=1))

    with _run_at(_SUNDAY_EVENING):
        with patch(
            "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
        ) as mock_post:
            await weekly_review.run()
            await weekly_review.run()

    mock_post.assert_called_once()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_no_op_leaves_no_dedup_row_and_a_later_sunday_tick_still_sends(db):
    with _run_at(_SUNDAY_AFTERNOON):
        with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
            await weekly_review.run()
    mock_post.assert_not_called()

    with _run_at(_SUNDAY_EVENING):
        with patch(
            "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
        ) as mock_post:
            await weekly_review.run()
    mock_post.assert_called_once()
