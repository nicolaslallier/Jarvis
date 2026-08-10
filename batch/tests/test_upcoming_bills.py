from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest
from jarvis_shared.db import Base
from jarvis_shared.models import Bill
from sqlalchemy import select

from app.db import async_session, engine
from app.health_state import state
from app.jobs import upcoming_bills

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
    with patch("app.jobs.upcoming_bills.get_settings", return_value=_FakeSettings()):
        yield


def _today() -> datetime:
    return datetime.now(_TZ)


async def _add_bill(
    name: str, amount: str, due_day: int, recurrence: str = "monthly", created_at: datetime | None = None
) -> Bill:
    async with async_session() as session:
        bill = Bill(
            name=name,
            amount=Decimal(amount),
            due_day=due_day,
            recurrence=recurrence,
        )
        session.add(bill)
        await session.commit()
        await session.refresh(bill)
        if created_at is not None:
            # created_at has a server_default — overwrite it directly so
            # yearly-recurrence tests can control the anchor month without
            # depending on when the test happens to run.
            bill.created_at = created_at
            await session.commit()
            await session.refresh(bill)
        return bill


def _canned_ntfy_response() -> httpx.Response:
    return httpx.Response(200, request=httpx.Request("POST", "https://ntfy.test/jarvis-test-topic"))


@pytest.mark.asyncio
async def test_bill_due_in_exactly_lead_days_is_notified(db):
    due_date = (_today() + timedelta(days=upcoming_bills.BILL_REMINDER_LEAD_DAYS)).date()
    await _add_bill("Electricite", "125.50", due_date.day, "monthly")

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await upcoming_bills.run()

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://ntfy.test/jarvis-test-topic"
    assert kwargs["headers"]["Title"] == "Rappel Jarvis"
    body = kwargs["content"].decode("utf-8")
    assert "Electricite" in body
    assert "125.50" in body
    assert due_date.isoformat() in body
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_running_again_same_day_does_not_renotify(db):
    due_date = (_today() + timedelta(days=upcoming_bills.BILL_REMINDER_LEAD_DAYS)).date()
    await _add_bill("Internet", "80.00", due_date.day, "monthly")

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await upcoming_bills.run()
        await upcoming_bills.run()

    mock_post.assert_called_once()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_bill_outside_lead_window_is_not_notified(db):
    far_due_date = (_today() + timedelta(days=upcoming_bills.BILL_REMINDER_LEAD_DAYS + 10)).date()
    await _add_bill("Assurance", "200.00", far_due_date.day, "monthly")

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await upcoming_bills.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_bill_just_notified_is_not_notified_again(db):
    # Lead day is 1 short of the window — should not be notified.
    near_due_date = (_today() + timedelta(days=upcoming_bills.BILL_REMINDER_LEAD_DAYS - 1)).date()
    await _add_bill("Trop tot", "15.00", near_due_date.day, "monthly")

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        await upcoming_bills.run()

    mock_post.assert_not_called()
    assert state.last_status == "ok"


@pytest.mark.asyncio
async def test_yearly_bill_due_in_lead_days_is_notified(db):
    today = _today()
    due_date = (today + timedelta(days=upcoming_bills.BILL_REMINDER_LEAD_DAYS)).date()
    # created_at's month is the anchor month for a yearly bill.
    created_at = datetime(today.year - 1, due_date.month, 1, tzinfo=_TZ)
    await _add_bill("Renouvellement", "300.00", due_date.day, "yearly", created_at=created_at)

    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=_canned_ntfy_response())
    ) as mock_post:
        await upcoming_bills.run()

    mock_post.assert_called_once()
    assert state.last_status == "ok"


def test_compute_due_date_monthly_rolls_to_next_month_when_passed():
    today = datetime(2026, 8, 20, tzinfo=_TZ).date()
    bill = Bill(name="x", amount=Decimal("1.00"), due_day=5, recurrence="monthly")
    due = upcoming_bills.compute_due_date(bill, today)
    assert due.year == 2026
    assert due.month == 9
    assert due.day == 5


def test_compute_due_date_monthly_same_month_when_not_yet_passed():
    today = datetime(2026, 8, 1, tzinfo=_TZ).date()
    bill = Bill(name="x", amount=Decimal("1.00"), due_day=20, recurrence="monthly")
    due = upcoming_bills.compute_due_date(bill, today)
    assert due == datetime(2026, 8, 20, tzinfo=_TZ).date()


def test_compute_due_date_clamps_short_month():
    today = datetime(2026, 2, 1, tzinfo=_TZ).date()
    bill = Bill(name="x", amount=Decimal("1.00"), due_day=31, recurrence="monthly")
    due = upcoming_bills.compute_due_date(bill, today)
    assert due == datetime(2026, 2, 28, tzinfo=_TZ).date()
