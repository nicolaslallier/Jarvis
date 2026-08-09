from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import calendar_service
from app.db import get_db
from app.models import Appointment
from app.schemas import AppointmentCreate, AppointmentRead, AppointmentUpdate

router = APIRouter()


@router.post("/calendar/appointments", response_model=AppointmentRead)
async def create_appointment(
    appointment: AppointmentCreate, db: AsyncSession = Depends(get_db)
) -> Appointment:
    return await calendar_service.create_appointment(db, **appointment.model_dump())


@router.get("/calendar/appointments", response_model=list[AppointmentRead])
async def list_appointments(
    start: datetime | None = None, end: datetime | None = None, db: AsyncSession = Depends(get_db)
) -> list[Appointment]:
    return await calendar_service.list_appointments(db, start=start, end=end)


@router.get("/calendar/appointments/{appointment_id}", response_model=AppointmentRead)
async def get_appointment(appointment_id: int, db: AsyncSession = Depends(get_db)) -> Appointment:
    appointment = await calendar_service.get_appointment(db, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="appointment not found")
    return appointment


@router.put("/calendar/appointments/{appointment_id}", response_model=AppointmentRead)
async def update_appointment(
    appointment_id: int, appointment: AppointmentUpdate, db: AsyncSession = Depends(get_db)
) -> Appointment:
    updated = await calendar_service.update_appointment(
        db, appointment_id, **appointment.model_dump(exclude_unset=True)
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="appointment not found")
    return updated


@router.delete("/calendar/appointments/{appointment_id}", status_code=204)
async def delete_appointment(appointment_id: int, db: AsyncSession = Depends(get_db)) -> None:
    deleted = await calendar_service.delete_appointment(db, appointment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="appointment not found")
