from datetime import UTC, datetime

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task

_OPEN_STATUSES = ("todo", "doing")
# Same ordering as routers/tasks.py: open tasks first (soonest due date,
# then undated), done/cancelled tasks trail at the bottom.
_TASK_ORDER = (
    case((Task.status.in_(_OPEN_STATUSES), 0), else_=1),
    Task.due_at.is_(None),
    Task.due_at,
    Task.id,
)


async def list_tasks(
    db: AsyncSession, *, status: str | None = None, project: str | None = None
) -> list[Task]:
    stmt = select(Task).order_by(*_TASK_ORDER)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if project is not None:
        stmt = stmt.where(Task.project == project)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_task(db: AsyncSession, task_id: int) -> Task | None:
    return await db.get(Task, task_id)


async def create_task(
    db: AsyncSession,
    *,
    title: str,
    description: str | None = None,
    due_at: datetime | None = None,
    priority: str = "normal",
    project: str | None = None,
    tags: list[str] | None = None,
    parent_id: int | None = None,
) -> Task:
    task = Task(
        title=title,
        description=description,
        due_at=due_at,
        priority=priority,
        project=project,
        tags=tags,
        parent_id=parent_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def update_task(db: AsyncSession, task_id: int, **fields: object) -> Task | None:
    task = await db.get(Task, task_id)
    if task is None:
        return None
    if "status" in fields and fields["status"] is not None and fields["status"] != task.status:
        fields["completed_at"] = datetime.now(UTC) if fields["status"] == "done" else None
    for field, value in fields.items():
        if value is not None or field == "completed_at":
            setattr(task, field, value)
    await db.commit()
    await db.refresh(task)
    return task


async def complete_task(db: AsyncSession, task_id: int) -> Task | None:
    return await update_task(db, task_id, status="done")


async def fetch_active(db: AsyncSession, limit: int = 20) -> list[Task]:
    """Open (todo/doing) tasks, soonest-due first, used to give the chat
    model task awareness without it having to call a tool just to answer
    "what's on my plate" style questions."""
    stmt = (
        select(Task)
        .where(Task.status.in_(_OPEN_STATUSES))
        .order_by(Task.due_at.is_(None), Task.due_at, Task.id)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def format_active_context(tasks: list[Task]) -> str:
    lines = [
        f"[{t.id}] {t.title}"
        + (f" — due {t.due_at.isoformat()}" if t.due_at else "")
        + (f" ({t.priority} priority)" if t.priority != "normal" else "")
        + (f" [{t.project}]" if t.project else "")
        for t in tasks
    ]
    return (
        "The user's open tasks (id, title, due date if set, priority if "
        "not normal, and project if set) are listed below. Use them to "
        "inform your answer when relevant; ignore them if they aren't, "
        "and don't mention that this list was 'provided' to you.\n\n"
        + "\n".join(lines)
    )
