from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Item
from app.schemas import ItemCreate, ItemRead

router = APIRouter()


@router.post("/items", response_model=ItemRead)
async def create_item(item: ItemCreate, db: AsyncSession = Depends(get_db)) -> Item:
    db_item = Item(name=item.name)
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item


@router.get("/items", response_model=list[ItemRead])
async def list_items(db: AsyncSession = Depends(get_db)) -> list[Item]:
    result = await db.execute(select(Item).order_by(Item.id))
    return list(result.scalars().all())
