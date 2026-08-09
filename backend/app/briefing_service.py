"""Builds the "briefing du jour" (daily briefing): today's appointments,
tasks due today, overdue tasks, and a best-effort LLM-generated French
summary paragraph in the voice of the user's personal secretary.

Mirrors app/calendar_service.py and app/task_service.py's plain-async-
function style (not a class), and app/routers/chat.py's _generate_title
pattern for the best-effort LM Studio call: any failure there just means
`summary` comes back `None`, never a reason the endpoint fails.
"""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import calendar_service
from app.config import Settings
from app.models import Appointment, Task

logger = logging.getLogger(__name__)

SUMMARY_TIMEOUT_SECONDS = 30.0

# Same open-status convention as app/task_service.py's _OPEN_STATUSES.
_OPEN_STATUSES = ("todo", "doing")

SUMMARY_SYSTEM_PROMPT = (
    "You are the user's personal secretary. Below is a compact list of "
    "today's appointments and open tasks (due today or overdue). Write ONE "
    "short paragraph in French, in the warm but efficient voice of a "
    "personal secretary greeting the user by name (Nicolas) at the start of "
    "the day, e.g. \"Bonjour Nicolas, aujourd'hui vous avez...\". Mention "
    "the appointments and tasks naturally, flag anything overdue, and keep "
    "it to 2-4 sentences of plain prose — no bullet points, no headers, no "
    "markdown."
)

# Returned locally (no LM Studio call) when there is nothing at all to
# summarize, to save a pointless round-trip.
_EMPTY_DAY_SUMMARY = (
    "Bonjour Nicolas, vous n'avez rien de prévu aujourd'hui — aucun rendez-vous "
    "ni tâche urgente. Profitez-en pour avancer à votre rythme."
)


def _local_today_bounds(settings: Settings) -> tuple[datetime, datetime, datetime]:
    """Returns (today_start_utc, today_end_utc, now_local): the user's local
    calendar day, expressed both as UTC bounds (for querying columns stored
    in UTC) and as the local "now" (for the `date` field). Falls back to UTC
    if the configured timezone name is invalid — same fallback pattern as
    app/routers/chat.py's _build_datetime_context.
    """
    now_utc = datetime.now(UTC)
    try:
        tz = ZoneInfo(settings.timezone)
    except Exception:
        logger.warning("Unknown TIMEZONE %r, falling back to UTC", settings.timezone)
        tz = UTC
    now_local = now_utc.astimezone(tz)
    local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = local_midnight.astimezone(UTC)
    today_end_utc = (local_midnight + timedelta(days=1)).astimezone(UTC)
    return today_start_utc, today_end_utc, now_local


async def _fetch_due_today_tasks(
    db: AsyncSession, today_start_utc: datetime, today_end_utc: datetime
) -> list[Task]:
    """Open tasks whose due_at falls within today's local calendar day."""
    stmt = (
        select(Task)
        .where(Task.status.in_(_OPEN_STATUSES))
        .where(Task.due_at.is_not(None))
        .where(Task.due_at >= today_start_utc)
        .where(Task.due_at < today_end_utc)
        .order_by(Task.due_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _fetch_overdue_tasks(db: AsyncSession, today_start_utc: datetime) -> list[Task]:
    """Open tasks whose due_at is before today's local calendar day."""
    stmt = (
        select(Task)
        .where(Task.status.in_(_OPEN_STATUSES))
        .where(Task.due_at.is_not(None))
        .where(Task.due_at < today_start_utc)
        .order_by(Task.due_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _format_summary_prompt(
    appointments: list[Appointment], due_tasks: list[Task], overdue_tasks: list[Task]
) -> str:
    lines: list[str] = []
    if appointments:
        lines.append("Rendez-vous d'aujourd'hui :")
        lines.extend(
            f"- {a.start_time.isoformat()} : {a.title}" for a in appointments
        )
    if due_tasks:
        lines.append("Tâches à faire aujourd'hui :")
        lines.extend(f"- {t.title}" for t in due_tasks)
    if overdue_tasks:
        lines.append("Tâches en retard :")
        lines.extend(f"- {t.title}" for t in overdue_tasks)
    return "\n".join(lines)


async def _generate_summary(
    settings: Settings,
    appointments: list[Appointment],
    due_tasks: list[Task],
    overdue_tasks: list[Task],
) -> str | None:
    """Best-effort: asks the chat model for a short French summary
    paragraph. Any failure (LM Studio unreachable, bad response) just means
    `summary` comes back None — never a reason GET /briefing fails."""
    try:
        prompt = _format_summary_prompt(appointments, due_tasks, overdue_tasks)
        async with httpx.AsyncClient(timeout=SUMMARY_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.lmstudio_base_url}/v1/chat/completions",
                json={
                    "model": settings.lmstudio_model,
                    "messages": [
                        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 200,
                },
            )
        if response.status_code != 200:
            logger.warning("Briefing summary call returned %s", response.status_code)
            return None
        content = response.json()["choices"][0]["message"]["content"]
        content = content.strip() if content else ""
        return content or None
    except Exception:
        logger.warning("Briefing summary generation failed", exc_info=True)
        return None


async def build_briefing(db: AsyncSession, settings: Settings) -> dict:
    """Assembles today's briefing: appointments, due-today tasks, overdue
    tasks, and a best-effort French summary paragraph. Returns a plain dict
    matching BriefingRead's shape."""
    today_start_utc, today_end_utc, now_local = _local_today_bounds(settings)

    appointments = await calendar_service.list_appointments(
        db, start=today_start_utc, end=today_end_utc
    )
    due_tasks = await _fetch_due_today_tasks(db, today_start_utc, today_end_utc)
    overdue_tasks = await _fetch_overdue_tasks(db, today_start_utc)

    if not appointments and not due_tasks and not overdue_tasks:
        # Nothing to summarize — skip the LLM call entirely to save a
        # pointless round-trip.
        summary = _EMPTY_DAY_SUMMARY
    else:
        summary = await _generate_summary(settings, appointments, due_tasks, overdue_tasks)

    return {
        "date": now_local.date().isoformat(),
        "appointments": appointments,
        "due_tasks": due_tasks,
        "overdue_tasks": overdue_tasks,
        "summary": summary,
    }
