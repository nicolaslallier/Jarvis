from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact


async def list_contacts(db: AsyncSession) -> list[Contact]:
    result = await db.execute(select(Contact).order_by(Contact.name))
    return list(result.scalars().all())


async def get_contact(db: AsyncSession, contact_id: int) -> Contact | None:
    return await db.get(Contact, contact_id)


async def create_contact(
    db: AsyncSession,
    *,
    name: str,
    date: date,
    date_type: str,
    recurring_yearly: bool = True,
    reminder_lead_days: int = 7,
) -> Contact:
    contact = Contact(
        name=name,
        date=date,
        date_type=date_type,
        recurring_yearly=recurring_yearly,
        reminder_lead_days=reminder_lead_days,
    )
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return contact


async def update_contact(db: AsyncSession, contact_id: int, **fields: object) -> Contact | None:
    contact = await db.get(Contact, contact_id)
    if contact is None:
        return None
    for field, value in fields.items():
        if value is not None:
            setattr(contact, field, value)
    await db.commit()
    await db.refresh(contact)
    return contact


async def delete_contact(db: AsyncSession, contact_id: int) -> bool:
    contact = await db.get(Contact, contact_id)
    if contact is None:
        return False
    await db.delete(contact)
    await db.commit()
    return True
