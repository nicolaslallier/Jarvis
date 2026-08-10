"""Recurring-bill due-date reminders: notifies the user via ntfy when a
bill's *computed* next due date is exactly BILL_REMINDER_LEAD_DAYS away.
There's no stored per-cycle due date (see jarvis_shared.models.Bill's
docstring on why this feature is deliberately "lite") — the due date for
"this cycle" is derived from `due_day`/`recurrence` fresh on every run.

Dedup is DB-backed via the same `notifications_sent` table reminders.py
uses (kind="bill_due", entity_id=bill.id, notified_date=today), so a bill
already notified about today stays suppressed across scheduler ticks and
container restarts — same pattern as app/jobs/reminders.py.
"""

import calendar
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from jarvis_shared.models import Bill, NotificationSent
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import async_session
from app.health_state import state
from app.notifier import send_ntfy

logger = logging.getLogger(__name__)

# How many days before a bill's computed due date to send the reminder.
# A single, sensible lead time rather than a per-bill setting — see
# CLAUDE.md's task description for this "lite" pass.
BILL_REMINDER_LEAD_DAYS = 3

_BILL_KIND = "bill_due"

# Same portable-across-Postgres-and-SQLite UPSERT as reminders.py's
# _MARK_NOTIFIED_SQL.
_MARK_NOTIFIED_SQL = text(
    "INSERT INTO notifications_sent (kind, entity_id, notified_date) "
    "VALUES (:kind, :entity_id, :notified_date) "
    "ON CONFLICT (kind, entity_id, notified_date) DO NOTHING"
)


def _clamped_date(year: int, month: int, day: int) -> date:
    """Clamps `day` to the last valid day of (year, month) — e.g. a
    due_day of 31 in a 30-day month becomes the 30th, rather than raising
    on an invalid calendar date."""
    last_day_of_month = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day_of_month))


def compute_due_date(bill: Bill, today: date) -> date:
    """This cycle's due date for `bill`, rolling forward to the next cycle
    if this cycle's date has already passed (strictly before `today` — a
    bill due today is still this cycle's, not next's).

    monthly: this month's `due_day`, rolled to next month if already past.
    yearly: `due_day` in the same month as `bill.created_at`, current
    year, rolled to next year if already past. Kept deliberately simple
    per CLAUDE.md — monthly is the common case.
    """
    if bill.recurrence == "yearly":
        anchor_month = bill.created_at.month
        candidate = _clamped_date(today.year, anchor_month, bill.due_day)
        if candidate < today:
            candidate = _clamped_date(today.year + 1, anchor_month, bill.due_day)
        return candidate

    # "monthly" and any other/unrecognized value default to monthly — same
    # no-DB-enum, don't-crash-on-a-free-string convention used elsewhere
    # (e.g. Task.status) in this codebase.
    candidate = _clamped_date(today.year, today.month, bill.due_day)
    if candidate < today:
        next_month = 1 if today.month == 12 else today.month + 1
        next_year = today.year + 1 if today.month == 12 else today.year
        candidate = _clamped_date(next_year, next_month, bill.due_day)
    return candidate


async def _fetch_bills() -> list[Bill]:
    async with async_session() as session:
        result = await session.execute(select(Bill))
        return list(result.scalars().all())


async def _filter_unnotified(session: AsyncSession, bills: list[Bill], today: date) -> list[Bill]:
    """Drops any bill already recorded in notifications_sent for
    (kind="bill_due", bill.id, today). Same IN-clause approach as
    reminders.py's _filter_unnotified, so it works against both the
    Postgres this job runs against in production and the SQLite the test
    suite uses."""
    if not bills:
        return []
    ids = [bill.id for bill in bills]
    result = await session.execute(
        select(NotificationSent.entity_id).where(
            NotificationSent.kind == _BILL_KIND,
            NotificationSent.notified_date == today,
            NotificationSent.entity_id.in_(ids),
        )
    )
    notified_ids = {row[0] for row in result}
    return [bill for bill in bills if bill.id not in notified_ids]


async def _mark_notified(session: AsyncSession, bill: Bill, today: date) -> None:
    await session.execute(
        _MARK_NOTIFIED_SQL, {"kind": _BILL_KIND, "entity_id": bill.id, "notified_date": today}
    )


def _format_message(bill: Bill, due_date: date) -> str:
    return f"Rappel: {bill.name} ({bill.amount}$) est du le {due_date.isoformat()}"


async def run() -> None:
    logger.info("upcoming_bills: checking for bills due in %d day(s)", BILL_REMINDER_LEAD_DAYS)
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()

    try:
        bills = await _fetch_bills()
    except Exception:
        logger.exception("upcoming_bills: failed to query bills")
        state.record("error")
        return

    due_soon = [
        (bill, due_date)
        for bill in bills
        for due_date in [compute_due_date(bill, today)]
        if (due_date - today).days == BILL_REMINDER_LEAD_DAYS
    ]

    if not due_soon:
        logger.info("upcoming_bills: no bills due in %d day(s)", BILL_REMINDER_LEAD_DAYS)
        state.record("ok")
        return

    try:
        async with async_session() as session:
            unnotified_ids = {
                bill.id
                for bill in await _filter_unnotified(session, [b for b, _ in due_soon], today)
            }
    except Exception:
        logger.exception("upcoming_bills: failed to query notifications_sent for dedup")
        state.record("error")
        return

    due_soon = [(bill, due_date) for bill, due_date in due_soon if bill.id in unnotified_ids]

    if not due_soon:
        logger.info("upcoming_bills: nothing new to notify")
        state.record("ok")
        return

    notified_count = 0
    for bill, due_date in due_soon:
        try:
            await send_ntfy(settings, title="Rappel Jarvis", message=_format_message(bill, due_date))
        except Exception:
            # send_ntfy is already best-effort internally and shouldn't
            # raise, but guard here too so one bill's notification failure
            # never blocks the rest, or fails the job overall.
            logger.exception("upcoming_bills: send_ntfy call failed unexpectedly for bill %d", bill.id)
            continue

        try:
            async with async_session() as session:
                await _mark_notified(session, bill, today)
                await session.commit()
        except Exception:
            # The notification already went out successfully at this
            # point, so this failure shouldn't be reported as the job
            # failing overall — worst case, an unrecorded dedup row means
            # the same bill can be re-notified on the next tick, which is
            # safe, just noisy.
            logger.exception(
                "upcoming_bills: failed to record notifications_sent after successful send for bill %d",
                bill.id,
            )
        else:
            notified_count += 1

    logger.info("upcoming_bills: notified %d bill(s)", notified_count)
    state.record("ok")
