from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import briefing_service
from app.config import get_settings
from app.db import get_db
from app.schemas import BriefingRead

router = APIRouter()


@router.get("/briefing", response_model=BriefingRead)
async def get_briefing(db: AsyncSession = Depends(get_db)) -> dict:
    return await briefing_service.build_briefing(db, get_settings())
