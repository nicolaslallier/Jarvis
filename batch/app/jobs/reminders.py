"""Proactive reminders job: notifies the user via ntfy.sh about overdue
tasks and tomorrow's appointments, once per scheduler tick.

Dedup note: there is no DB table tracking "already notified" items (adding
one would need a new Alembic migration, and migrations are owned by another
agent working in parallel — see shared/jarvis_shared/migrations/). Instead
we keep an in-memory module-level map of (kind, id) -> last-notified local
date string, so the same task/appointment isn't re-notified again within the
same local calendar day even though this job re-runs every
`reminder_job_interval_minutes`. This resets on container restart (a stopped
task/appointment can be re-notified the same day after a restart) — a rare,
acceptable tradeoff for a homelab tool, not worth over-engineering further.
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from jarvis_shared.models import Appointment, Task
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.health_state import state
from app.notifier import send_ntfy

logger = logging.getLogger(__name__)

_OPEN_STATUSES = ("todo", "doing")

# (kind, id) -> ISO date string (local) this item was last notified on.
_last_notified: dict[tuple[str, int], str] = {}


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


def _filter_unnotified(items: list, kind: str, today_str: str) -> list:
    fresh = []
    for item in items:
        key = (kind, item.id)
        if _last_notified.get(key) == today_str:
            continue
        fresh.append(item)
    return fresh


def _mark_notified(items: list, kind: str, today_str: str) -> None:
    for item in items:
        _last_notified[(kind, item.id)] = today_str


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
    today_str = now_local.date().isoformat()

    try:
        now_utc = now_local.astimezone(timezone.utc)
        overdue_tasks = await _fetch_overdue_tasks(now_utc)

        tomorrow_start, tomorrow_end = _tomorrow_window(now_local)
        tomorrow_appts = await _fetch_tomorrow_appointments(tomorrow_start, tomorrow_end)
    except Exception:
        logger.exception("reminders: failed to query overdue tasks / tomorrow's appointments")
        state.record("error")
        return

    overdue_tasks = _filter_unnotified(overdue_tasks, "task", today_str)
    tomorrow_appts = _filter_unnotified(tomorrow_appts, "appointment", today_str)

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

    _mark_notified(overdue_tasks, "task", today_str)
    _mark_notified(tomorrow_appts, "appointment", today_str)

    logger.info(
        "reminders: notified %d overdue task(s), %d tomorrow appointment(s)",
        len(overdue_tasks),
        len(tomorrow_appts),
    )
    state.record("ok")
