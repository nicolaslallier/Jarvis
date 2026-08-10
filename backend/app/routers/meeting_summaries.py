"""CRUD surface for meeting summaries — see app/meeting_summaries.py's
module docstring for why every query goes through raw SQL instead of the
ORM.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.embeddings import embed_text
from app.meeting_summaries import (
    create_meeting_summary,
    delete_meeting_summary,
    embed_source_text,
    get_meeting_summary,
    list_meeting_summaries,
    update_meeting_summary,
)
from app.schemas import MeetingSummaryCreate, MeetingSummaryRead, MeetingSummaryUpdate

router = APIRouter()


@router.post("/meeting-summaries", response_model=MeetingSummaryRead)
async def create_meeting_summary_endpoint(
    payload: MeetingSummaryCreate, db: AsyncSession = Depends(get_db)
):
    embedding = await embed_text(embed_source_text(payload.title, payload.content))
    if embedding is None:
        raise HTTPException(status_code=502, detail="could not embed meeting summary")

    return await create_meeting_summary(
        db,
        title=payload.title,
        meeting_date=payload.meeting_date,
        content=payload.content,
        participants=payload.participants,
        appointment_id=payload.appointment_id,
        embedding=embedding,
    )


@router.get("/meeting-summaries", response_model=list[MeetingSummaryRead])
async def list_meeting_summaries_endpoint(db: AsyncSession = Depends(get_db)):
    return await list_meeting_summaries(db)


@router.get("/meeting-summaries/{meeting_summary_id}", response_model=MeetingSummaryRead)
async def get_meeting_summary_endpoint(meeting_summary_id: int, db: AsyncSession = Depends(get_db)):
    row = await get_meeting_summary(db, meeting_summary_id)
    if row is None:
        raise HTTPException(status_code=404, detail="meeting summary not found")
    return row


@router.put("/meeting-summaries/{meeting_summary_id}", response_model=MeetingSummaryRead)
async def update_meeting_summary_endpoint(
    meeting_summary_id: int, payload: MeetingSummaryUpdate, db: AsyncSession = Depends(get_db)
):
    current = await get_meeting_summary(db, meeting_summary_id)
    if current is None:
        raise HTTPException(status_code=404, detail="meeting summary not found")

    fields = payload.model_dump(exclude_unset=True)
    title = fields.get("title", current.title)
    meeting_date = fields.get("meeting_date", current.meeting_date)
    content = fields.get("content", current.content)
    participants = fields.get("participants", current.participants)
    appointment_id = fields.get("appointment_id", current.appointment_id)

    embedding = await embed_text(embed_source_text(title, content))
    if embedding is None:
        raise HTTPException(status_code=502, detail="could not re-embed meeting summary")

    return await update_meeting_summary(
        db,
        meeting_summary_id,
        title=title,
        meeting_date=meeting_date,
        content=content,
        participants=participants,
        appointment_id=appointment_id,
        embedding=embedding,
    )


@router.delete("/meeting-summaries/{meeting_summary_id}", status_code=204)
async def delete_meeting_summary_endpoint(meeting_summary_id: int, db: AsyncSession = Depends(get_db)) -> None:
    deleted = await delete_meeting_summary(db, meeting_summary_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="meeting summary not found")
