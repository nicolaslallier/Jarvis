from fastapi import APIRouter, HTTPException

from app.db import check_connection

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    try:
        await check_connection()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unreachable: {exc}") from exc
    return {"status": "ok", "database": "up"}
