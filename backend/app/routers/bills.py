from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Bill
from app.schemas import BillCreate, BillRead, BillUpdate

router = APIRouter()


@router.post("/bills", response_model=BillRead)
async def create_bill(bill: BillCreate, db: AsyncSession = Depends(get_db)) -> Bill:
    db_bill = Bill(**bill.model_dump())
    db.add(db_bill)
    await db.commit()
    await db.refresh(db_bill)
    return db_bill


@router.get("/bills", response_model=list[BillRead])
async def list_bills(db: AsyncSession = Depends(get_db)) -> list[Bill]:
    result = await db.execute(select(Bill).order_by(Bill.due_day, Bill.id))
    return list(result.scalars().all())


@router.put("/bills/{bill_id}", response_model=BillRead)
async def update_bill(bill_id: int, bill: BillUpdate, db: AsyncSession = Depends(get_db)) -> Bill:
    db_bill = await db.get(Bill, bill_id)
    if db_bill is None:
        raise HTTPException(status_code=404, detail="bill not found")
    fields = bill.model_dump(exclude_unset=True)
    for field, value in fields.items():
        setattr(db_bill, field, value)
    await db.commit()
    await db.refresh(db_bill)
    return db_bill


@router.delete("/bills/{bill_id}", status_code=204)
async def delete_bill(bill_id: int, db: AsyncSession = Depends(get_db)) -> None:
    db_bill = await db.get(Bill, bill_id)
    if db_bill is None:
        raise HTTPException(status_code=404, detail="bill not found")
    await db.delete(db_bill)
    await db.commit()
