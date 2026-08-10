from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import habit_service
from app.db import get_db
from app.models import Habit
from app.schemas import HabitCreate, HabitRead

router = APIRouter()


@router.post("/habits", response_model=HabitRead)
async def create_habit(habit: HabitCreate, db: AsyncSession = Depends(get_db)) -> Habit:
    return await habit_service.create_habit(db, name=habit.name, frequency=habit.frequency)


@router.get("/habits", response_model=list[HabitRead])
async def list_habits(db: AsyncSession = Depends(get_db)) -> list[Habit]:
    return await habit_service.list_habits(db)


@router.post("/habits/{habit_id}/complete", response_model=HabitRead)
async def complete_habit(habit_id: int, db: AsyncSession = Depends(get_db)) -> Habit:
    db_habit = await habit_service.complete_habit(db, habit_id)
    if db_habit is None:
        raise HTTPException(status_code=404, detail="habit not found")
    return db_habit


@router.delete("/habits/{habit_id}", status_code=204)
async def delete_habit(habit_id: int, db: AsyncSession = Depends(get_db)) -> None:
    deleted = await habit_service.delete_habit(db, habit_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="habit not found")
