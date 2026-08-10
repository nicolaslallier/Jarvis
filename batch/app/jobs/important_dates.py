"""Important-dates reminder job: notifies the user via ntfy about upcoming
contact dates (birthdays, anniversaries, renewals, ...) based on each
Contact's own `reminder_lead_days`.

Dedup is DB-backed via the same `notifications_sent` table reminders.py /
upcoming_bills.py use (kind="contact_date", entity_id=contact.id,
notified_date=today), so a contact date already notified about today stays
suppressed across scheduler ticks and container restarts — same pattern as
app/jobs/reminders.py.
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis_shared.models import Contact, NotificationSent
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import async_session
from app.health_state import state
from app.notifier import send_ntfy

logger = logging.getLogger(__name__)

_KIND = "contact_date"

# Same portable-across-Postgres-and-SQLite UPSERT as reminders.py's /
# upcoming_bills.py's _MARK_NOTIFIED_SQL.
_MARK_NOTIFIED_SQL = text(
    "INSERT INTO notifications_sent (kind, entity_id, notified_date) "
    "VALUES (:kind, :entity_id, :notified_date) "
    "ON CONFLICT (kind, entity_id, notified_date) DO NOTHING"
)


def next_occurrence(contact: Contact, today: date) -> date:
    """This year's (or, if it already passed, next year's) occurrence of
    `contact.date` for a recurring_yearly contact — month/day held fixed,
    year rolled forward until the occurrence is on or after `today`. For a
    non-recurring contact, `contact.date` is used as-is, since there's only
    ever one occurrence."""
    if not contact.recurring_yearly:
        return contact.date

    occurrence = contact.date.replace(year=today.year)
    if occurrence < today:
        occurrence = occurrence.replace(year=today.year + 1)
    return occurrence


async def _fetch_contacts() -> list[Contact]:
    async with async_session() as session:
        result = await session.execute(select(Contact))
        return list(result.scalars().all())


async def _filter_unnotified(session: AsyncSession, contacts: list[Contact], today: date) -> list[Contact]:
    """Drops any contact already recorded in notifications_sent for
    (kind="contact_date", contact.id, today). Same IN-clause approach as
    reminders.py's _filter_unnotified, so it works against both the
    Postgres this job runs against in production and the SQLite the test
    suite uses."""
    if not contacts:
        return []
    ids = [contact.id for contact in contacts]
    result = await session.execute(
        select(NotificationSent.entity_id).where(
            NotificationSent.kind == _KIND,
            NotificationSent.notified_date == today,
            NotificationSent.entity_id.in_(ids),
        )
    )
    notified_ids = {row[0] for row in result}
    return [contact for contact in contacts if contact.id not in notified_ids]


async def _mark_notified(session: AsyncSession, contact: Contact, today: date) -> None:
    await session.execute(
        _MARK_NOTIFIED_SQL, {"kind": _KIND, "entity_id": contact.id, "notified_date": today}
    )


def _format_message(contact: Contact) -> str:
    return f"Rappel : l'anniversaire de {contact.name} est dans {contact.reminder_lead_days} jours"


async def run() -> None:
    logger.info("important_dates: checking for contacts due for a reminder")
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()

    try:
        contacts = await _fetch_contacts()
    except Exception:
        logger.exception("important_dates: failed to query contacts")
        state.record("error")
        return

    due = [
        contact
        for contact in contacts
        if next_occurrence(contact, today) - timedelta(days=contact.reminder_lead_days) == today
    ]

    if not due:
        logger.info("important_dates: no contact dates due for a reminder today")
        state.record("ok")
        return

    try:
        async with async_session() as session:
            due = await _filter_unnotified(session, due, today)
    except Exception:
        logger.exception("important_dates: failed to query notifications_sent for dedup")
        state.record("error")
        return

    if not due:
        logger.info("important_dates: nothing new to notify")
        state.record("ok")
        return

    notified_count = 0
    for contact in due:
        try:
            await send_ntfy(settings, title="Rappel Jarvis", message=_format_message(contact))
        except Exception:
            # send_ntfy is already best-effort internally and shouldn't
            # raise, but guard here too so one contact's notification
            # failure never blocks the rest, or fails the job overall.
            logger.exception(
                "important_dates: send_ntfy call failed unexpectedly for contact %d", contact.id
            )
            continue

        try:
            async with async_session() as session:
                await _mark_notified(session, contact, today)
                await session.commit()
        except Exception:
            # The notification already went out successfully at this point,
            # so this failure shouldn't be reported as the job failing
            # overall — worst case, an unrecorded dedup row means the same
            # contact can be re-notified on the next tick, which is safe,
            # just noisy.
            logger.exception(
                "important_dates: failed to record notifications_sent after successful send "
                "for contact %d",
                contact.id,
            )
        else:
            notified_count += 1

    logger.info("important_dates: notified %d contact date(s)", notified_count)
    state.record("ok")
