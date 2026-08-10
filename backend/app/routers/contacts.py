from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import contact_service
from app.db import get_db
from app.models import Contact
from app.schemas import ContactCreate, ContactRead, ContactUpdate

router = APIRouter()


@router.post("/contacts", response_model=ContactRead)
async def create_contact(contact: ContactCreate, db: AsyncSession = Depends(get_db)) -> Contact:
    return await contact_service.create_contact(db, **contact.model_dump())


@router.get("/contacts", response_model=list[ContactRead])
async def list_contacts(db: AsyncSession = Depends(get_db)) -> list[Contact]:
    return await contact_service.list_contacts(db)


@router.put("/contacts/{contact_id}", response_model=ContactRead)
async def update_contact(
    contact_id: int, contact: ContactUpdate, db: AsyncSession = Depends(get_db)
) -> Contact:
    updated = await contact_service.update_contact(
        db, contact_id, **contact.model_dump(exclude_unset=True)
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="contact not found")
    return updated


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: int, db: AsyncSession = Depends(get_db)) -> None:
    deleted = await contact_service.delete_contact(db, contact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="contact not found")
