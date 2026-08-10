"""CRUD surface for the Memory page: lets the user view, correct, or delete
the durable facts app/memory.py's extraction path (driven from
app/routers/chat.py) has learned about them across conversations. See
app/memory.py's module docstring for why every query here goes through raw
SQL instead of the ORM.
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.embeddings import embed_text
from app.memory import delete_memory, list_memories, store_journal_memory, update_memory_content
from app.schemas import MemoryCreate, MemoryCreateRead, MemoryRead, MemoryUpdate

logger = logging.getLogger(__name__)

router = APIRouter()

EMBEDDING_TIMEOUT_SECONDS = 30.0


async def _embed_text(settings: Settings, content: str) -> list[float] | None:
    """Embeds `content` via LM Studio for PATCH /memories/{id} specifically
    — kept as its own copy (rather than app/embeddings.py's shared
    embed_text, used by POST /memories below) since this one still takes an
    explicit `settings` rather than calling get_settings() internally.
    Same best-effort-return-None-on-failure shape either way; a None here is
    NOT swallowed by the caller: PATCH /memories/{id} below turns it into a
    hard 502, since a stale/wrong embedding after an edit is worse than
    failing the edit.
    """
    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.embedding_lmstudio_base_url}/v1/embeddings",
                json={"model": settings.embedding_lmstudio_model, "input": [content]},
            )
        if response.status_code != 200:
            logger.warning("Embedding call returned %s", response.status_code)
            return None
        return response.json()["data"][0]["embedding"]
    except Exception:
        logger.warning("Embedding call failed", exc_info=True)
        return None


@router.get("/memories", response_model=list[MemoryRead])
async def get_memories(db: AsyncSession = Depends(get_db)) -> list:
    return await list_memories(db)


@router.post("/memories", response_model=MemoryCreateRead)
async def create_journal_memory(payload: MemoryCreate, db: AsyncSession = Depends(get_db)):
    """Lets the user write a journal/quick-note directly, stored as a
    Memory row (source='journal') so it's retrieved by chat like any other
    memory. Unlike the best-effort retrieval/extraction embedding calls
    elsewhere, this fails loudly (502) if LM Studio is unreachable — the
    user explicitly asked to save this note right now, so silently
    dropping it would be worse than telling them it failed.
    """
    embedding = await embed_text(payload.content)
    if embedding is None:
        raise HTTPException(status_code=502, detail="could not embed journal note")

    return await store_journal_memory(db, payload.content, embedding)


@router.patch("/memories/{memory_id}", response_model=MemoryRead)
async def patch_memory(
    memory_id: int, payload: MemoryUpdate, db: AsyncSession = Depends(get_db)
):
    settings = get_settings()
    embedding = await _embed_text(settings, payload.content)
    if embedding is None:
        raise HTTPException(status_code=502, detail="could not re-embed updated memory")

    row = await update_memory_content(db, memory_id, payload.content, embedding)
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return row


@router.delete("/memories/{memory_id}", status_code=204)
async def remove_memory(memory_id: int, db: AsyncSession = Depends(get_db)) -> None:
    deleted = await delete_memory(db, memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="memory not found")
