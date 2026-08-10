from dataclasses import dataclass
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest
from jarvis_shared.db import Base
from jarvis_shared.models import Contact
from sqlalchemy import select, text

from app.db import async_session, engine
from app.health_state import state
from app.jobs import important_dates

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
    with patch("app.jobs.important_dates.get_settings", return_value=_FakeSettings()):
        yield


def _today() -> date:
    return datetime.now(_TZ).date()


async def _add_contact(
    name: str,
    contact_date: date,
    *,
    date_type: str = "birthday",
    recurring_yearly: bool = True,
    reminder_lead_days: int = 7,
) -> Contact:
    async with async_session() as session:
        contact = Contact(
            name=name,
            date=contact_date,
            date_type=date_type,
            recurring_yearly=recurring_yearly,
            reminder_lead_days=reminder_lead_days,
        )
        session.add(contact)
        await session.commit()
        await session.refresh(contact)
        return contact


def _canned_ntfy_response() -> httpx.Response:
    return httpx.Response(200, request=httpx.Request("POST", "https://ntfy.test/jarvis-test-topic"))


@pytest.mark.asyncio
async def test_contact_due_today_is_notified(db):
    # Non-recurring date, exactly reminder_lead_days away — the reminder
    # (occurrence - lead_days) lands on today.
    lead_days = 7
    occurrence = _today() + timedelta(days=lead_days)
    await _add_contact(
        "Alice", occurrence, recurring_yearly=False, reminder_lead_days=lead_days
    )

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await important_dates.run()

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://ntfy.test/jarvis-test-topic"
    assert kwargs["headers"]["Title"] == "Rappel Jarvis"
    body = kwargs["content"].decode("utf-8")
    assert "Alice" in body
    assert "7" in body
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_running_again_same_day_does_not_renotify(db):
    occurrence = _today() + timedelta(days=3)
    await _add_contact("Bob", occurrence, recurring_yearly=False, reminder_lead_days=3)

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await important_dates.run()
        await important_dates.run()

    mock_post.assert_called_once()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_contact_not_due_today_is_not_notified(db):
    occurrence = _today() + timedelta(days=20)
    await _add_contact("Carol", occurrence, recurring_yearly=False, reminder_lead_days=3)

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await important_dates.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_notification_persists_dedup_across_a_fresh_session(db):
    """Same guarantee as reminders.py's own restart-safety test: a dedup row
    written by some earlier, now-closed session must still suppress the
    notification the very first time important_dates.run() executes
    afterwards."""
    occurrence = _today() + timedelta(days=5)
    contact = await _add_contact("Dana", occurrence, recurring_yearly=False, reminder_lead_days=5)

    today = _today()
    async with async_session() as session:
        await session.execute(
            text(
                "INSERT INTO notifications_sent (kind, entity_id, notified_date) "
                "VALUES (:kind, :entity_id, :notified_date)"
            ),
            {"kind": "contact_date", "entity_id": contact.id, "notified_date": today},
        )
        await session.commit()

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await important_dates.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


def test_next_occurrence_recurring_rolls_to_next_year_when_passed():
    today = date(2026, 8, 9)
    contact = Contact(
        name="X", date=date(2000, 1, 15), date_type="birthday", recurring_yearly=True, reminder_lead_days=7
    )
    assert important_dates.next_occurrence(contact, today) == date(2027, 1, 15)


def test_next_occurrence_recurring_stays_this_year_if_upcoming():
    today = date(2026, 8, 9)
    contact = Contact(
        name="X", date=date(2000, 12, 25), date_type="birthday", recurring_yearly=True, reminder_lead_days=7
    )
    assert important_dates.next_occurrence(contact, today) == date(2026, 12, 25)


def test_next_occurrence_non_recurring_uses_stored_date_as_is():
    contact = Contact(
        name="X", date=date(2030, 3, 1), date_type="renewal", recurring_yearly=False, reminder_lead_days=7
    )
    assert important_dates.next_occurrence(contact, date(2026, 8, 9)) == date(2030, 3, 1)


@pytest.mark.asyncio
async def test_recurring_yearly_contact_rolled_to_next_year_is_notified(db):
    # A recurring date whose month/day already passed earlier this year (it
    # fell "yesterday") forces the job to roll it forward to *next* year's
    # occurrence — set reminder_lead_days to land the reminder for that
    # rolled-forward occurrence exactly on today, proving the rollover
    # branch (not just "this year's date is still upcoming") drives the
    # notification.
    today = _today()
    yesterday = today - timedelta(days=1)
    # Arbitrary anchor year: only month/day matter for a recurring contact.
    contact_date = date(2000, yesterday.month, yesterday.day)
    rolled_occurrence = date(today.year + 1, yesterday.month, yesterday.day)
    lead_days = (rolled_occurrence - today).days

    await _add_contact(
        "Eve", contact_date, recurring_yearly=True, reminder_lead_days=lead_days
    )

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await important_dates.run()

    mock_post.assert_called_once()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_multiple_due_contacts_are_all_notified_independently(db):
    lead_days = 2
    occurrence = _today() + timedelta(days=lead_days)
    await _add_contact("First", occurrence, recurring_yearly=False, reminder_lead_days=lead_days)
    await _add_contact("Second", occurrence, recurring_yearly=False, reminder_lead_days=lead_days)

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await important_dates.run()

    assert mock_post.call_count == 2
    assert state.last_status == "ok"

    async with async_session() as session:
        result = await session.execute(select(Contact))
        assert len(list(result.scalars().all())) == 2
