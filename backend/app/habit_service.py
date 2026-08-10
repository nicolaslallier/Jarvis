from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Habit

# Grace windows around each frequency's nominal period, generous enough that
# a habit done slightly late/early (e.g. 11pm one day, 7am the next) still
# counts as consecutive, but tight enough that a multi-day lapse still
# breaks the streak. Deliberately a small if/elif on the free-text
# `frequency` string, not a general recurrence engine — see habit_service's
# module docstring in CLAUDE.md.
_STREAK_WINDOWS = {
    "daily": timedelta(days=2),
    "weekly": timedelta(days=9),
}
_DEFAULT_STREAK_WINDOW = timedelta(days=2)


async def list_habits(db: AsyncSession) -> list[Habit]:
    result = await db.execute(select(Habit).order_by(Habit.id))
    return list(result.scalars().all())


async def create_habit(db: AsyncSession, *, name: str, frequency: str) -> Habit:
    habit = Habit(name=name, frequency=frequency)
    db.add(habit)
    await db.commit()
    await db.refresh(habit)
    return habit


async def delete_habit(db: AsyncSession, habit_id: int) -> bool:
    habit = await db.get(Habit, habit_id)
    if habit is None:
        return False
    await db.delete(habit)
    await db.commit()
    return True


async def complete_habit(db: AsyncSession, habit_id: int) -> Habit | None:
    habit = await db.get(Habit, habit_id)
    if habit is None:
        return None

    now = datetime.now(UTC)
    if habit.last_completed_at is None:
        habit.streak_count = 1
    else:
        window = _STREAK_WINDOWS.get(habit.frequency, _DEFAULT_STREAK_WINDOW)
        last_completed = habit.last_completed_at
        if last_completed.tzinfo is None:
            # SQLite (tests) round-trips DateTime(timezone=True) columns as
            # naive; treat a naive stored value as UTC, matching `now` above.
            last_completed = last_completed.replace(tzinfo=UTC)
        gap = now - last_completed
        if gap <= window:
            habit.streak_count += 1
        else:
            habit.streak_count = 1
    habit.last_completed_at = now

    await db.commit()
    await db.refresh(habit)
    return habit
