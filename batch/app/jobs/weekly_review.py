"""Weekly review job: sends a Sunday-evening summary of the past week's
completed tasks, current overdue tasks, and the coming week's due tasks via
ntfy.

The scheduler ticks this job as often as any other registered job (see
app/jobs/__init__.py's registered_jobs()), but it must actually SEND at most
once per calendar week. Two independent gates enforce that:

1. A local-time weekday/hour check, before anything else runs: the job
   no-ops unless `settings.timezone`'s local time is Sunday at or after
   `_SUNDAY_EVENING_HOUR`. This mirrors reminders.py's/upcoming_bills.py's/
   important_dates.py's `ZoneInfo(settings.timezone)`-based local-time
   convention (the only local-timezone convention this codebase has) rather
   than gating on naive UTC, so "Sunday evening" means the user's actual
   Sunday evening, not whatever weekday UTC happens to be at that moment.
2. The same `notifications_sent` dedup table reminders.py / upcoming_bills.py
   / important_dates.py use, with `kind="weekly_review"`. Unlike those jobs
   (which dedupe per-entity, per-day), this review has exactly one instance
   per week and no per-entity id, so `entity_id` is the constant
   `_ENTITY_ID = 0`, and `notified_date` is the Monday that starts the
   current ISO week rather than `today` — that's what keeps the dedup key
   stable across every tick inside the Sunday-evening window (however many
   there are, depending on how the tick interval lines up), so only the
   first one actually sends.

Known simplification: like the other jobs above, "evening" is resolved in
`settings.timezone`'s local time only — there's no per-user timezone
preference beyond that single IANA zone (a homelab, single-household app).
"""

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from jarvis_shared.models import NotificationSent, Task
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import async_session
from app.health_state import state
from app.notifier import send_ntfy

logger = logging.getLogger(__name__)

_KIND = "weekly_review"
_ENTITY_ID = 0  # Constant: there's only ever one weekly review, no per-entity id applies.
_SUNDAY_WEEKDAY = 6  # datetime.weekday(): Monday=0 ... Sunday=6.
_SUNDAY_EVENING_HOUR = 18  # Local 24h hour at/after which the review is eligible to send.

# Tasks in either of these statuses are considered "closed" and excluded
# from the overdue/upcoming sections — same status vocabulary as
# jarvis_shared.models.TASK_STATUSES.
_CLOSED_STATUSES = ("done", "cancelled")

# Same portable-across-Postgres-and-SQLite UPSERT as reminders.py's /
# upcoming_bills.py's / important_dates.py's _MARK_NOTIFIED_SQL.
_MARK_NOTIFIED_SQL = text(
    "INSERT INTO notifications_sent (kind, entity_id, notified_date) "
    "VALUES (:kind, :entity_id, :notified_date) "
    "ON CONFLICT (kind, entity_id, notified_date) DO NOTHING"
)


def _week_monday(today: date) -> date:
    """The Monday that starts `today`'s ISO week. Used as the dedup
    `notified_date` instead of `today` itself, so the key stays the same
    across every tick inside the Sunday-evening window regardless of
    exactly which tick fires."""
    return today - timedelta(days=today.weekday())


def _is_sunday_evening(now_local: datetime) -> bool:
    return now_local.weekday() == _SUNDAY_WEEKDAY and now_local.hour >= _SUNDAY_EVENING_HOUR


async def _fetch_completed_tasks(start_utc: datetime, end_utc: datetime) -> list[Task]:
    async with async_session() as session:
        result = await session.execute(
            select(Task).where(
                Task.status == "done",
                Task.completed_at >= start_utc,
                Task.completed_at < end_utc,
            )
        )
        return list(result.scalars().all())


async def _fetch_overdue_tasks(now_utc: datetime) -> list[Task]:
    async with async_session() as session:
        result = await session.execute(
            select(Task).where(Task.status.notin_(_CLOSED_STATUSES), Task.due_at < now_utc)
        )
        return list(result.scalars().all())


async def _fetch_upcoming_tasks(start_utc: datetime, end_utc: datetime) -> list[Task]:
    async with async_session() as session:
        result = await session.execute(
            select(Task).where(
                Task.status.notin_(_CLOSED_STATUSES),
                Task.due_at >= start_utc,
                Task.due_at < end_utc,
            )
        )
        return list(result.scalars().all())


async def _already_sent_this_week(session: AsyncSession, week_monday: date) -> bool:
    result = await session.execute(
        select(NotificationSent.id).where(
            NotificationSent.kind == _KIND,
            NotificationSent.entity_id == _ENTITY_ID,
            NotificationSent.notified_date == week_monday,
        )
    )
    return result.first() is not None


async def _mark_notified(session: AsyncSession, week_monday: date) -> None:
    await session.execute(
        _MARK_NOTIFIED_SQL,
        {"kind": _KIND, "entity_id": _ENTITY_ID, "notified_date": week_monday},
    )


def _format_section(title: str, tasks: list[Task]) -> list[str]:
    lines = [f"{title} ({len(tasks)}) :"]
    if tasks:
        lines.extend(f"- {task.title}" for task in tasks)
    else:
        lines.append("- Aucune")
    return lines


def _format_message(completed: list[Task], overdue: list[Task], upcoming: list[Task]) -> str:
    lines: list[str] = ["Bilan hebdomadaire :", ""]
    lines.extend(_format_section("Tâches complétées cette semaine", completed))
    lines.append("")
    lines.extend(_format_section("Tâches en retard", overdue))
    lines.append("")
    lines.extend(_format_section("Tâches à venir cette semaine", upcoming))
    return "\n".join(lines)


async def run() -> None:
    logger.info("weekly_review: checking whether it's Sunday evening")
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    now_local = datetime.now(tz)

    if not _is_sunday_evening(now_local):
        logger.info("weekly_review: not Sunday evening (local), skipping")
        state.record("ok")
        return

    week_monday = _week_monday(now_local.date())

    try:
        async with async_session() as session:
            already_sent = await _already_sent_this_week(session, week_monday)
    except Exception:
        logger.exception("weekly_review: failed to query notifications_sent for dedup")
        state.record("error")
        return

    if already_sent:
        logger.info("weekly_review: already sent for week of %s", week_monday.isoformat())
        state.record("ok")
        return

    now_utc = now_local.astimezone(timezone.utc)
    week_ago_utc = now_utc - timedelta(days=7)
    week_ahead_utc = now_utc + timedelta(days=7)

    try:
        completed = await _fetch_completed_tasks(week_ago_utc, now_utc)
        overdue = await _fetch_overdue_tasks(now_utc)
        upcoming = await _fetch_upcoming_tasks(now_utc, week_ahead_utc)
    except Exception:
        logger.exception("weekly_review: failed to query tasks")
        state.record("error")
        return

    message = _format_message(completed, overdue, upcoming)

    try:
        await send_ntfy(settings, title="Bilan hebdomadaire Jarvis", message=message)
    except Exception:
        # send_ntfy is already best-effort internally and shouldn't raise,
        # but guard here too so a notification failure never fails the job.
        logger.exception("weekly_review: send_ntfy call failed unexpectedly")
        state.record("error")
        return

    try:
        async with async_session() as session:
            await _mark_notified(session, week_monday)
            await session.commit()
    except Exception:
        # The notification already went out successfully at this point, so
        # this failure shouldn't be reported as the job failing overall —
        # worst case, an unrecorded dedup row means the review can be
        # re-sent on a later tick within the same Sunday-evening window,
        # which is safe, just noisy.
        logger.exception("weekly_review: failed to record notifications_sent after successful send")

    logger.info(
        "weekly_review: sent summary for week of %s (%d completed, %d overdue, %d upcoming)",
        week_monday.isoformat(),
        len(completed),
        len(overdue),
        len(upcoming),
    )
    state.record("ok")
