"""Proactive-suggestions job: surfaces two things the user hasn't asked
about but probably wants to know without opening the chat —

- Calendar conflicts: pairs of upcoming Appointment rows whose
  [start_time, end_time] ranges overlap.
- Stale tasks: open Task rows nobody has touched in a while.

Dedup is DB-backed via the same `notifications_sent` table
app/jobs/reminders.py / important_dates.py / upcoming_bills.py use, so
already-notified items stay suppressed across scheduler ticks and container
restarts. The two checks use different dedup windows though (see each
section below), since "don't repeat today" and "don't repeat this week"
are different guarantees for different kinds of noise.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from jarvis_shared.models import Appointment, NotificationSent, Task
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import async_session
from app.health_state import state
from app.notifier import send_ntfy

logger = logging.getLogger(__name__)

_CONFLICT_KIND = "calendar_conflict"
_STALE_KIND = "stale_task"

# How far ahead to look for overlapping appointments. Two weeks is enough to
# catch double-bookings made well in advance without scanning the whole
# calendar every tick.
_CONFLICT_WINDOW_DAYS = 14

# A pair of overlapping appointments is encoded as a single Integer for
# notifications_sent.entity_id (that column has no room for a composite
# key) as `low.id * _PAIR_ID_MULTIPLIER + high.id`, where `low`/`high` are
# the pair sorted by id ascending. Sorting first means the same pair always
# encodes to the same value regardless of which order the O(n^2) scan below
# discovers it in. This assumes appointment ids stay below 100,000, a
# reasonable ceiling for a single-user homelab app's appointments table; if
# that's ever exceeded, two *different* pairs could collide onto the same
# encoded id, which only risks suppressing one of their notifications a
# tick early (fails safe — never fails to notify, just possibly a little
# late), not any data corruption.
_PAIR_ID_MULTIPLIER = 100_000

# A task open (not done/cancelled/pending_review) for this many days since
# creation without being touched is considered "stale". Task has no
# updated_at column (see shared/jarvis_shared/models.py), so created_at is
# the only signal available — this therefore really means "created more
# than N days ago and still open", not "untouched for N days", but it's the
# best proxy available until Task grows an updated_at column.
_STALE_TASK_THRESHOLD_DAYS = 21

# Same statuses reminders.py's overdue-task check *excludes* the inverse
# of (_OPEN_STATUSES there is ("todo", "doing")) — spelled out here as an
# exclusion list instead so a newly-added open-ish status defaults to being
# flagged as stale rather than silently ignored.
_STALE_EXCLUDED_STATUSES = ("done", "cancelled", "pending_review")

# Same portable-across-Postgres-and-SQLite UPSERT as reminders.py's /
# important_dates.py's / upcoming_bills.py's _MARK_NOTIFIED_SQL.
_MARK_NOTIFIED_SQL = text(
    "INSERT INTO notifications_sent (kind, entity_id, notified_date) "
    "VALUES (:kind, :entity_id, :notified_date) "
    "ON CONFLICT (kind, entity_id, notified_date) DO NOTHING"
)


def _conflict_pair_id(low: Appointment, high: Appointment) -> int:
    """Deterministic single-int id for a conflicting appointment pair. See
    the _PAIR_ID_MULTIPLIER comment above for the encoding and its
    assumptions. Caller must pass `low`/`high` already sorted by id."""
    return low.id * _PAIR_ID_MULTIPLIER + high.id


def _week_start(day: date) -> date:
    """Monday of the local calendar week containing `day`, used as the
    notified_date for stale-task dedup so a given task can fire at most
    once per week rather than once per day."""
    return day - timedelta(days=day.weekday())


async def _fetch_upcoming_appointments(now_utc: datetime, window_end_utc: datetime) -> list[Appointment]:
    async with async_session() as session:
        result = await session.execute(
            select(Appointment)
            .where(Appointment.start_time <= window_end_utc, Appointment.end_time >= now_utc)
            .order_by(Appointment.start_time)
        )
        return list(result.scalars().all())


def _find_conflicts(appointments: list[Appointment]) -> list[tuple[Appointment, Appointment]]:
    """O(n^2) pairwise overlap scan — fine for a single-user calendar's
    within-two-weeks appointment count. Two ranges [s1, e1) and [s2, e2)
    overlap iff s1 < e2 and s2 < e1. Each returned pair is sorted
    (low.id, high.id) so _conflict_pair_id is stable regardless of scan
    order."""
    conflicts: list[tuple[Appointment, Appointment]] = []
    for i, a in enumerate(appointments):
        for b in appointments[i + 1 :]:
            if a.start_time < b.end_time and b.start_time < a.end_time:
                pair = (a, b) if a.id < b.id else (b, a)
                conflicts.append(pair)
    return conflicts


async def _fetch_stale_tasks(cutoff_utc: datetime) -> list[Task]:
    async with async_session() as session:
        result = await session.execute(
            select(Task).where(
                Task.status.notin_(_STALE_EXCLUDED_STATUSES),
                Task.created_at < cutoff_utc,
            )
        )
        return list(result.scalars().all())


async def _already_notified_ids(
    session: AsyncSession, kind: str, entity_ids: list[int], notified_date: date
) -> set[int]:
    """Same IN-clause approach as reminders.py's _filter_unnotified, so it
    works against both the Postgres this job runs against in production and
    the SQLite the test suite uses."""
    if not entity_ids:
        return set()
    result = await session.execute(
        select(NotificationSent.entity_id).where(
            NotificationSent.kind == kind,
            NotificationSent.notified_date == notified_date,
            NotificationSent.entity_id.in_(entity_ids),
        )
    )
    return {row[0] for row in result}


async def _mark_notified(session: AsyncSession, kind: str, entity_id: int, notified_date: date) -> None:
    await session.execute(
        _MARK_NOTIFIED_SQL, {"kind": kind, "entity_id": entity_id, "notified_date": notified_date}
    )


def _format_conflict_message(low: Appointment, high: Appointment) -> str:
    return (
        f'Conflit d\'horaire : "{low.title}" '
        f"({low.start_time.strftime('%d/%m %H:%M')}–{low.end_time.strftime('%H:%M')}) "
        f'chevauche "{high.title}" '
        f"({high.start_time.strftime('%d/%m %H:%M')}–{high.end_time.strftime('%H:%M')})"
    )


def _format_stale_tasks_message(tasks: list[Task]) -> str:
    lines = [f"Tâches sans avancement depuis plus de {_STALE_TASK_THRESHOLD_DAYS} jours :"]
    for task in tasks:
        lines.append(f"- {task.title}")
    return "\n".join(lines)


async def _check_calendar_conflicts(settings: Settings, now_utc: datetime, today: date) -> None:
    window_end_utc = now_utc + timedelta(days=_CONFLICT_WINDOW_DAYS)
    appointments = await _fetch_upcoming_appointments(now_utc, window_end_utc)
    conflicts = _find_conflicts(appointments)
    if not conflicts:
        return

    pair_ids = [_conflict_pair_id(low, high) for low, high in conflicts]
    async with async_session() as session:
        notified_ids = await _already_notified_ids(session, _CONFLICT_KIND, pair_ids, today)

    unnotified = [
        (low, high, pid) for (low, high), pid in zip(conflicts, pair_ids) if pid not in notified_ids
    ]
    if not unnotified:
        return

    notified_count = 0
    for low, high, pid in unnotified:
        try:
            await send_ntfy(
                settings, title="Conflit d'horaire", message=_format_conflict_message(low, high)
            )
        except Exception:
            # send_ntfy is already best-effort internally and shouldn't
            # raise, but guard here too so one pair's notification failure
            # never blocks the rest.
            logger.exception(
                "proactive_suggestions: send_ntfy failed for conflict pair (%d, %d)", low.id, high.id
            )
            continue

        try:
            async with async_session() as session:
                await _mark_notified(session, _CONFLICT_KIND, pid, today)
                await session.commit()
        except Exception:
            # The notification already went out successfully at this point,
            # so this failure shouldn't fail the job overall — worst case,
            # an unrecorded dedup row means the same pair can be
            # re-notified on the next tick, which is safe, just noisy.
            logger.exception(
                "proactive_suggestions: failed to record notification for conflict pair (%d, %d)",
                low.id,
                high.id,
            )
        else:
            notified_count += 1

    logger.info("proactive_suggestions: notified %d calendar conflict pair(s)", notified_count)


async def _check_stale_tasks(settings: Settings, now_utc: datetime, today: date) -> None:
    cutoff_utc = now_utc - timedelta(days=_STALE_TASK_THRESHOLD_DAYS)
    stale_tasks = await _fetch_stale_tasks(cutoff_utc)
    if not stale_tasks:
        return

    week_start = _week_start(today)
    task_ids = [task.id for task in stale_tasks]
    async with async_session() as session:
        notified_ids = await _already_notified_ids(session, _STALE_KIND, task_ids, week_start)

    unnotified = [task for task in stale_tasks if task.id not in notified_ids]
    if not unnotified:
        return

    try:
        await send_ntfy(
            settings, title="Tâches en pause", message=_format_stale_tasks_message(unnotified)
        )
    except Exception:
        # send_ntfy is already best-effort internally and shouldn't raise,
        # but guard here too so a notification failure never fails the job.
        logger.exception("proactive_suggestions: send_ntfy failed for stale tasks")
        return

    try:
        async with async_session() as session:
            for task in unnotified:
                await _mark_notified(session, _STALE_KIND, task.id, week_start)
            await session.commit()
    except Exception:
        # Same reasoning as the conflict-pair path above: the notification
        # already went out, so a dedup-write failure here is logged but
        # doesn't fail the job.
        logger.exception("proactive_suggestions: failed to record notifications for stale tasks")
        return

    logger.info("proactive_suggestions: notified about %d stale task(s)", len(unnotified))


async def run() -> None:
    logger.info("proactive_suggestions: checking for calendar conflicts and stale tasks")
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)
    now_local = datetime.now(tz)
    today = now_local.date()
    now_utc = now_local.astimezone(timezone.utc)

    # The two checks are independent — a failure in one (bad query, ntfy
    # down, dedup-table hiccup) shouldn't prevent the other from running.
    had_error = False

    try:
        await _check_calendar_conflicts(settings, now_utc, today)
    except Exception:
        logger.exception("proactive_suggestions: calendar conflict check failed")
        had_error = True

    try:
        await _check_stale_tasks(settings, now_utc, today)
    except Exception:
        logger.exception("proactive_suggestions: stale task check failed")
        had_error = True

    state.record("error" if had_error else "ok")
