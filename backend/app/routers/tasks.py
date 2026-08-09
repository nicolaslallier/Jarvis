from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Task
from app.schemas import TaskCreate, TaskRead, TaskUpdate

router = APIRouter()


@router.post("/tasks", response_model=TaskRead)
async def create_task(task: TaskCreate, db: AsyncSession = Depends(get_db)) -> Task:
    db_task = Task(title=task.title, description=task.description, due_date=task.due_date)
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    return db_task


@router.get("/tasks", response_model=list[TaskRead])
async def list_tasks(db: AsyncSession = Depends(get_db)) -> list[Task]:
    result = await db.execute(select(Task).order_by(Task.id))
    return list(result.scalars().all())


@router.get("/tasks/count")
async def task_count(db: AsyncSession = Depends(get_db)) -> dict:
    """Return total, done, and active task counts in a single query."""
    result = await db.execute(
        select(
            func.count(Task.id).label("total"),
            func.sum(case((Task.done, 1), else_=0)).label("done"),
        )
    )
    row = result.one()
    total = row.total
    done = row.done or 0
    return {"total": total, "done": done, "active": total - done}


@router.post("/tasks/{task_id}/complete", response_model=TaskRead)
async def complete_task(task_id: int, db: AsyncSession = Depends(get_db)) -> Task:
    db_task = await db.get(Task, task_id)
    if db_task is None:
        raise HTTPException(status_code=404, detail="task not found")
    db_task.done = True
    await db.commit()
    await db.refresh(db_task)
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
    for field, value in task.model_dump(exclude_unset=True).items():
        setattr(db_task, field, value)
    await db.commit()
    await db.refresh(db_task)
    return db_task
