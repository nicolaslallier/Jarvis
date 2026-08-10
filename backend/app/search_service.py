"""Global search across the user's data: tasks, appointments, chat message
history, uploaded-file chunks (RAG), and remembered facts.

Two lookup strategies run side by side:

- Substring (`ILIKE`) match for tasks, appointments, and chat messages —
  no embedding needed, so these three legs always run and always succeed
  (barring a DB error, which propagates like any other query failure).
- Cosine-distance nearest-neighbor search for file_chunks and memories, via
  the exact `CAST(:query_vector AS vector)` raw-SQL pattern app/rag.py's
  fetch_relevant_chunks and app/memory.py's fetch_relevant_memories already
  use — NEVER the ORM `Vector` type, since the backend's engine
  deliberately doesn't register asyncpg's pgvector codec (see
  jarvis_shared/db.py's docstring). These two legs only run if `embed_fn`
  produces an embedding for the query; a failed/unreachable embedding call
  (or embed_fn raising outright) just means they're skipped, never a
  reason the whole search fails — same best-effort discipline as rag.py/
  memory.py's chat-context retrievals.

`score` is deliberately never unified across kinds: ILIKE-based results
have no notion of relevance ranking, so their score is `None`; vector-based
results carry their raw cosine distance (lower = closer). Mixing those into
one comparable number would be dishonest about what's actually being
measured.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings import embed_text
from app.models import Appointment, ChatMessageRecord, Task
from app.vector_format import format_vector_literal

EmbedFn = Callable[[str], Awaitable[list[float] | None]]

_SNIPPET_LENGTH = 200
_TITLE_LENGTH = 60

# ILIKE-based legs have no separate Settings fields (unlike the vector legs'
# SEARCH_CHUNK_TOP_K/SEARCH_MEMORY_TOP_K) — a substring match is cheap
# enough that a single generous constant is fine for all three.
_DEFAULT_ILIKE_LIMIT = 20


@dataclass
class SearchLimits:
    task_limit: int = _DEFAULT_ILIKE_LIMIT
    appointment_limit: int = _DEFAULT_ILIKE_LIMIT
    chat_message_limit: int = _DEFAULT_ILIKE_LIMIT
    chunk_top_k: int = 10
    memory_top_k: int = 10
    meeting_summary_top_k: int = 10


@dataclass
class SearchResult:
    kind: str
    id: int
    title: str
    snippet: str
    score: float | None


def _truncate(value: str, length: int) -> str:
    value = value.strip()
    return value if len(value) <= length else value[: length].rstrip() + "…"


_CHUNK_SEARCH_SQL = text(
    """
    SELECT fc.id, f.filename, fc.chunk_text,
           (fc.embedding <=> CAST(:query_vector AS vector)) AS distance
    FROM file_chunks fc
    JOIN files f ON f.id = fc.file_id
    ORDER BY distance ASC
    LIMIT :top_k
    """
)

_MEMORY_SEARCH_SQL = text(
    """
    SELECT id, content, (embedding <=> CAST(:query_vector AS vector)) AS distance
    FROM memories
    ORDER BY distance ASC
    LIMIT :top_k
    """
)

_MEETING_SUMMARY_SEARCH_SQL = text(
    """
    SELECT id, title, content, (embedding <=> CAST(:query_vector AS vector)) AS distance
    FROM meeting_summaries
    ORDER BY distance ASC
    LIMIT :top_k
    """
)


async def _search_tasks(db: AsyncSession, query: str, limit: int) -> list[SearchResult]:
    like = f"%{query}%"
    result = await db.execute(
        select(Task)
        .where(or_(Task.title.ilike(like), Task.description.ilike(like)))
        .order_by(Task.id.desc())
        .limit(limit)
    )
    return [
        SearchResult(
            kind="task",
            id=t.id,
            title=t.title,
            snippet=_truncate(t.description or t.title, _SNIPPET_LENGTH),
            score=None,
        )
        for t in result.scalars().all()
    ]


async def _search_appointments(db: AsyncSession, query: str, limit: int) -> list[SearchResult]:
    like = f"%{query}%"
    result = await db.execute(
        select(Appointment)
        .where(or_(Appointment.title.ilike(like), Appointment.description.ilike(like)))
        .order_by(Appointment.id.desc())
        .limit(limit)
    )
    return [
        SearchResult(
            kind="appointment",
            id=a.id,
            title=a.title,
            snippet=_truncate(a.description or a.title, _SNIPPET_LENGTH),
            score=None,
        )
        for a in result.scalars().all()
    ]


async def _search_chat_messages(db: AsyncSession, query: str, limit: int) -> list[SearchResult]:
    like = f"%{query}%"
    result = await db.execute(
        select(ChatMessageRecord)
        .where(ChatMessageRecord.content.ilike(like))
        .order_by(ChatMessageRecord.id.desc())
        .limit(limit)
    )
    return [
        SearchResult(
            kind="chat_message",
            id=m.id,
            title=_truncate(m.content, _TITLE_LENGTH),
            snippet=_truncate(m.content, _SNIPPET_LENGTH),
            score=None,
        )
        for m in result.scalars().all()
    ]


async def _search_file_chunks(db: AsyncSession, embedding: list[float], top_k: int) -> list[SearchResult]:
    result = await db.execute(
        _CHUNK_SEARCH_SQL, {"query_vector": format_vector_literal(embedding), "top_k": top_k}
    )
    return [
        SearchResult(
            kind="file_chunk",
            id=row.id,
            title=row.filename,
            snippet=_truncate(row.chunk_text, _SNIPPET_LENGTH),
            score=float(row.distance),
        )
        for row in result
    ]


async def _search_memories(db: AsyncSession, embedding: list[float], top_k: int) -> list[SearchResult]:
    result = await db.execute(
        _MEMORY_SEARCH_SQL, {"query_vector": format_vector_literal(embedding), "top_k": top_k}
    )
    return [
        SearchResult(
            kind="memory",
            id=row.id,
            title=_truncate(row.content, _TITLE_LENGTH),
            snippet=_truncate(row.content, _SNIPPET_LENGTH),
            score=float(row.distance),
        )
        for row in result
    ]


async def _search_meeting_summaries(
    db: AsyncSession, embedding: list[float], top_k: int
) -> list[SearchResult]:
    result = await db.execute(
        _MEETING_SUMMARY_SEARCH_SQL, {"query_vector": format_vector_literal(embedding), "top_k": top_k}
    )
    return [
        SearchResult(
            kind="meeting_summary",
            id=row.id,
            title=row.title,
            snippet=_truncate(row.content, _SNIPPET_LENGTH),
            score=float(row.distance),
        )
        for row in result
    ]


async def search(
    db: AsyncSession,
    embed_fn: EmbedFn,
    query: str,
    limits: SearchLimits,
) -> list[SearchResult]:
    """Runs every lookup and returns one flat list, section order stable
    (tasks, appointments, chat messages, file_chunks, memories, meeting
    summaries) — the caller (app/routers/search.py) groups by `kind` for
    display, not this function.

    The ILIKE-based legs (task/appointment/chat_message) always run. The
    vector-based legs (file_chunk/memory/meeting_summary) additionally need
    `embed_fn` to produce an embedding for `query`; if it returns None (LM
    Studio unreachable, bad response — see app/embeddings.py's embed_text)
    or raises outright, those legs are just skipped and every other leg's
    results still come back — an embedding failure is never a reason the
    whole search fails.
    """
    results: list[SearchResult] = []
    results += await _search_tasks(db, query, limits.task_limit)
    results += await _search_appointments(db, query, limits.appointment_limit)
    results += await _search_chat_messages(db, query, limits.chat_message_limit)

    try:
        embedding = await embed_fn(query)
    except Exception:
        embedding = None

    if embedding is not None:
        results += await _search_file_chunks(db, embedding, limits.chunk_top_k)
        results += await _search_memories(db, embedding, limits.memory_top_k)
        results += await _search_meeting_summaries(db, embedding, limits.meeting_summary_top_k)

    return results


async def search_with_defaults(db: AsyncSession, query: str, limits: SearchLimits) -> list[SearchResult]:
    """Convenience wrapper around `search()` that wires in the real LM
    Studio `embed_text` (app/embeddings.py) as `embed_fn`, so
    app/routers/search.py doesn't need to import app.embeddings itself just
    to call search(). `search()` itself keeps embed_fn as an explicit,
    required parameter (rather than defaulting it here too) so tests can
    inject a fake embed_fn without any LM Studio/httpx mocking at all.
    """
    return await search(db, embed_text, query, limits)
