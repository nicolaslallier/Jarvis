from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment


async def list_appointments(
    db: AsyncSession,
    start: datetime | None = None,
    end: datetime | None = None,
    pending_review: bool | None = None,
) -> list[Appointment]:
    stmt = select(Appointment).order_by(Appointment.start_time)
    if start is not None:
        stmt = stmt.where(Appointment.end_time >= start)
    if end is not None:
        stmt = stmt.where(Appointment.start_time <= end)
    if pending_review is not None:
        stmt = stmt.where(Appointment.pending_review == pending_review)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_appointment(db: AsyncSession, appointment_id: int) -> Appointment | None:
    return await db.get(Appointment, appointment_id)


async def create_appointment(
    db: AsyncSession,
    *,
    title: str,
    start_time: datetime,
    end_time: datetime,
    description: str | None = None,
    location: str | None = None,
    all_day: bool = False,
) -> Appointment:
    appointment = Appointment(
        title=title,
        description=description,
        location=location,
        start_time=start_time,
        end_time=end_time,
        all_day=all_day,
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def update_appointment(
    db: AsyncSession, appointment_id: int, **fields: object
) -> Appointment | None:
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None:
        return None
    for field, value in fields.items():
        if value is not None:
            setattr(appointment, field, value)
    await db.commit()
    await db.refresh(appointment)
    return appointment


async def delete_appointment(db: AsyncSession, appointment_id: int) -> bool:
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None:
        return False
    await db.delete(appointment)
    await db.commit()
    return True


async def fetch_upcoming(db: AsyncSession, days: int) -> list[Appointment]:
    """Appointments starting between now and `days` days from now, used to
    give the chat model calendar awareness without it having to call a tool
    just to answer "what's on my calendar" style questions."""
    now = datetime.now(UTC)
    return await list_appointments(db, start=now, end=now + timedelta(days=days))


def format_upcoming_context(appointments: list[Appointment]) -> str:
    lines = [
        f"[{a.id}] {a.title} — {a.start_time.isoformat()} to {a.end_time.isoformat()}"
        + (f" @ {a.location}" if a.location else "")
        for a in appointments
    ]
    return (
        "The user's upcoming appointments (id, title, start/end time, and "
        "location if set) are listed below. Use them to inform your answer "
        "when relevant; ignore them if they aren't, and don't mention that "
        "this list was 'provided' to you.\n\n" + "\n".join(lines)
    )
