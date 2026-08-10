from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import task_service
from app.db import get_db
from app.models import Task
from app.schemas import TaskCreate, TaskRead, TaskStatus, TaskUpdate

router = APIRouter()

# Open tasks (todo/doing) sort first, ordered by due date (soonest — and
# therefore overdue — first, undated tasks last), then done/cancelled tasks
# trail at the bottom. Ties within a group fall back to insertion order.
_OPEN_STATUSES = ("todo", "doing")
_CLOSED_GROUP_ORDER = case((Task.status.in_(_OPEN_STATUSES), 0), else_=1)
_TASK_ORDER = (
    _CLOSED_GROUP_ORDER,
    Task.due_at.is_(None),
    Task.due_at,
    Task.id,
)


@router.post("/tasks", response_model=TaskRead)
async def create_task(task: TaskCreate, db: AsyncSession = Depends(get_db)) -> Task:
    db_task = Task(**task.model_dump())
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    return db_task


@router.get("/tasks", response_model=list[TaskRead])
async def list_tasks(
    status: TaskStatus | None = None, db: AsyncSession = Depends(get_db)
) -> list[Task]:
    stmt = select(Task).order_by(*_TASK_ORDER)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/tasks/count")
async def task_count(db: AsyncSession = Depends(get_db)) -> dict:
    """Return total, done, and active (todo/doing) task counts in a single query."""
    result = await db.execute(
        select(
            func.count(Task.id).label("total"),
            func.sum(case((Task.status == "done", 1), else_=0)).label("done"),
            func.sum(case((Task.status.in_(_OPEN_STATUSES), 1), else_=0)).label("active"),
        )
    )
    row = result.one()
    return {"total": row.total, "done": row.done or 0, "active": row.active or 0}


@router.post("/tasks/{task_id}/complete", response_model=TaskRead)
async def complete_task(task_id: int, db: AsyncSession = Depends(get_db)) -> Task:
    # Delegates to task_service.complete_task (also used by chat.py's
    # complete_task tool call) rather than duplicating the status/
    # completed_at update here, since that's also where recurrence
    # regeneration lives — a completed recurring task should spawn its next
    # occurrence the same way regardless of which entry point completed it.
    db_task = await task_service.complete_task(db, task_id)
    if db_task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return db_task


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)) -> None:
    db_task = await db.get(Task, task_id)
    if db_task is None:
        raise HTTPException(status_code=404, detail="task not found")
    await db.delete(db_task)
    await db.commit()


@router.put("/tasks/{task_id}", response_model=TaskRead)
async def update_task(task_id: int, task: TaskUpdate, db: AsyncSession = Depends(get_db)) -> Task:
    db_task = await db.get(Task, task_id)
    if db_task is None:
        raise HTTPException(status_code=404, detail="task not found")
    fields = task.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] != db_task.status:
        # Reopening a task (todo/doing/cancelled) clears completed_at;
        # marking it done stamps it, unless the caller already provided one.
        if fields["status"] == "done":
            fields.setdefault("completed_at", datetime.now(UTC))
        else:
            fields.setdefault("completed_at", None)
    for field, value in fields.items():
        setattr(db_task, field, value)
    await db.commit()
    await db.refresh(db_task)
    return db_task
