"""Global search: GET /search?q=... across tasks, appointments, chat
message history, uploaded-file chunks (RAG), and remembered facts. All the
actual per-kind lookups live in app/search_service.py — this router just
resolves the configured limits from Settings and shapes the flat result
list into the response schema.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.schemas import SearchResponse, SearchResultRead
from app.search_service import SearchLimits, search_with_defaults

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def get_search(
    q: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)
) -> SearchResponse:
    settings = get_settings()
    limits = SearchLimits(
        chunk_top_k=settings.search_chunk_top_k,
        memory_top_k=settings.search_memory_top_k,
        meeting_summary_top_k=settings.search_meeting_summary_top_k,
    )
    results = await search_with_defaults(db, q, limits)
    return SearchResponse(
        query=q,
        results=[
            SearchResultRead(kind=r.kind, id=r.id, title=r.title, snippet=r.snippet, score=r.score)
            for r in results
        ],
    )
