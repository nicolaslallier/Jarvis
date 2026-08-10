"""Proactive reminders job: notifies the user via ntfy.sh about overdue
tasks and tomorrow's appointments, once per scheduler tick.

Dedup is DB-backed via the `notifications_sent` table (see migration
0009_notifications_sent.py / jarvis_shared.models.NotificationSent), so a
task/appointment already notified about today stays suppressed across
container restarts — unlike the previous in-memory map this replaced.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from jarvis_shared.models import Appointment, NotificationSent, Task
from sqlalchemy import select, text

from app.config import get_settings
from app.db import async_session
from app.health_state import state
from app.notifier import send_ntfy

logger = logging.getLogger(__name__)

_OPEN_STATUSES = ("todo", "doing")

# Portable across the Postgres this job runs against in production and the
# SQLite the test suite uses (both support the same UPSERT syntax as long as
# the conflict target matches a real unique index/constraint, which
# uq_notifications_sent_kind_entity_id_date does).
_MARK_NOTIFIED_SQL = text(
    "INSERT INTO notifications_sent (kind, entity_id, notified_date) "
    "VALUES (:kind, :entity_id, :notified_date) "
    "ON CONFLICT (kind, entity_id, notified_date) DO NOTHING"
)


async def _fetch_overdue_tasks(now_utc: datetime) -> list[Task]:
    async with async_session() as session:
        result = await session.execute(
            select(Task).where(Task.status.in_(_OPEN_STATUSES), Task.due_at < now_utc)
        )
        return list(result.scalars().all())


async def _fetch_tomorrow_appointments(start_utc: datetime, end_utc: datetime) -> list[Appointment]:
    async with async_session() as session:
        result = await session.execute(
            select(Appointment).where(
                Appointment.start_time >= start_utc, Appointment.start_time < end_utc
            )
        )
        return list(result.scalars().all())


def _tomorrow_window(now_local: datetime) -> tuple[datetime, datetime]:
    """Returns the [start, end) local-time bounds of "tomorrow" (the next
    local calendar day) as timezone-aware datetimes, so callers can compare
    directly against tz-aware `start_time` columns."""
    tomorrow_date = (now_local + timedelta(days=1)).date()
    start = datetime.combine(tomorrow_date, datetime.min.time(), tzinfo=now_local.tzinfo)
    end = start + timedelta(days=1)
    return start, end


async def _filter_unnotified(session, items: list, kind: str, today: date) -> list:
    """Drops any item already recorded in notifications_sent for (kind,
    item.id, today). Uses an IN clause (via the ORM query builder) rather
    than Postgres's ANY(:ids) so the same code path works against the
    SQLite the test suite runs on, not just the Postgres this job runs
    against in production."""
    if not items:
        return []
    ids = [item.id for item in items]
    result = await session.execute(
        select(NotificationSent.entity_id).where(
            NotificationSent.kind == kind,
            NotificationSent.notified_date == today,
            NotificationSent.entity_id.in_(ids),
        )
    )
    notified_ids = {row[0] for row in result}
    return [item for item in items if item.id not in notified_ids]


async def _mark_notified(session, items: list, kind: str, today: date) -> None:
    for item in items:
        await session.execute(
            _MARK_NOTIFIED_SQL, {"kind": kind, "entity_id": item.id, "notified_date": today}
        )


def _format_message(overdue_tasks: list[Task], tomorrow_appts: list[Appointment]) -> str:
    lines: list[str] = []
    if overdue_tasks:
        lines.append("Tâches en retard :")
        for task in overdue_tasks:
            lines.append(f"- {task.title}")
    if tomorrow_appts:
        if lines:
            lines.append("")
        lines.append("Rendez-vous de demain :")
        for appt in tomorrow_appts:
            lines.append(f"- {appt.title} ({appt.start_time.strftime('%H:%M')})")
    return "\n".join(lines)


async def run() -> None:
    logger.info("reminders: checking for overdue tasks and tomorrow's appointments")
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    now_local = datetime.now(tz)
    today = now_local.date()

    try:
        now_utc = now_local.astimezone(timezone.utc)
        overdue_tasks = await _fetch_overdue_tasks(now_utc)

        tomorrow_start, tomorrow_end = _tomorrow_window(now_local)
        tomorrow_appts = await _fetch_tomorrow_appointments(tomorrow_start, tomorrow_end)
    except Exception:
        logger.exception("reminders: failed to query overdue tasks / tomorrow's appointments")
        state.record("error")
        return

    try:
        async with async_session() as session:
            overdue_tasks = await _filter_unnotified(session, overdue_tasks, "task", today)
            tomorrow_appts = await _filter_unnotified(session, tomorrow_appts, "appointment", today)
    except Exception:
        logger.exception("reminders: failed to query notifications_sent for dedup")
        state.record("error")
        return

    if not overdue_tasks and not tomorrow_appts:
        logger.info("reminders: nothing new to notify")
        state.record("ok")
        return

    message = _format_message(overdue_tasks, tomorrow_appts)

    try:
        await send_ntfy(settings, title="Rappel Jarvis", message=message)
    except Exception:
        # send_ntfy is already best-effort internally and shouldn't raise,
        # but guard here too so a notification failure never fails the job.
        logger.exception("reminders: send_ntfy call failed unexpectedly")
        state.record("error")
        return

    try:
        async with async_session() as session:
            await _mark_notified(session, overdue_tasks, "task", today)
            await _mark_notified(session, tomorrow_appts, "appointment", today)
            await session.commit()
    except Exception:
        # The notification already went out successfully at this point, so
        # this failure shouldn't be reported as the job failing overall —
        # worst case, an unrecorded dedup row means the same item can be
        # re-notified on the next tick, which is safe, just noisy.
        logger.exception("reminders: failed to record notifications_sent after successful send")

    logger.info(
        "reminders: notified %d overdue task(s), %d tomorrow appointment(s)",
        len(overdue_tasks),
        len(tomorrow_appts),
    )
    state.record("ok")
