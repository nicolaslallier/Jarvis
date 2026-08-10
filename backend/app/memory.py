"""Cross-session memory: durable facts learned about the user from chat
exchanges, stored with embeddings and retrieved by relevance on later
messages/sessions — the counterpart to app/rag.py's file-chunk retrieval,
but for facts learned in conversation rather than uploaded documents.

Deliberately has no httpx/LM Studio calls of its own — app/routers/chat.py
owns all outbound LM Studio calls (embedding the query, asking the model to
extract facts, embedding those facts) the same way it already does for RAG,
and passes the results in here. This module is just the DB layer plus the
extraction reply parser.
"""

import json
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.vector_format import format_vector_literal

DEFAULT_TOP_K = 6

_SEARCH_SQL = text(
    """
    SELECT id, content, (embedding <=> CAST(:query_vector AS vector)) AS distance
    FROM memories
    ORDER BY distance ASC
    LIMIT :top_k
    """
)

# Raw SQL insert, not the ORM Memory model, for the same reason app/rag.py
# reads file_chunks via CAST(... AS vector) instead of the ORM Vector type:
# backend's engine deliberately doesn't register asyncpg's pgvector codec
# (see jarvis_shared/db.py), so writing through the ORM's Vector column
# would require it. Casting a plain string parameter sidesteps that.
_INSERT_SQL = text(
    """
    INSERT INTO memories (content, embedding, session_id)
    VALUES (:content, CAST(:embedding AS vector), :session_id)
    """
)

# Deliberately selects only these 4 columns, never `embedding` — listing
# memories for the Memory page never needs to touch the vector column, so
# this stays free of the pgvector codec requirement too (same reasoning as
# the module docstring above, just extended from writes to reads).
_LIST_SQL = text(
    """
    SELECT id, content, session_id, created_at
    FROM memories
    ORDER BY id DESC
    LIMIT :limit
    """
)

# Re-embedding on update is required, not optional: if the user edits a
# fact's text, the OLD embedding no longer matches the NEW content, which
# would silently corrupt future similarity retrieval (fetch_relevant_memories
# above). RETURNING lets a single round-trip double as the "does this id
# exist" check the router needs for its 404.
_UPDATE_SQL = text(
    """
    UPDATE memories
    SET content = :content, embedding = CAST(:embedding AS vector)
    WHERE id = :id
    RETURNING id, content, session_id, created_at
    """
)

_DELETE_SQL = text("DELETE FROM memories WHERE id = :id")

# Same raw-SQL CAST(... AS vector) pattern as _INSERT_SQL above, but for a
# journal note the user wrote directly (source='journal', no session_id)
# rather than a fact extracted from a chat exchange. Kept as its own
# statement/function rather than overloading store_memories: that function's
# signature (session_id + parallel facts/embeddings lists) is shaped for the
# batch extraction path and always leaves source NULL, neither of which fits
# a single journal entry with an explicit source.
_INSERT_JOURNAL_SQL = text(
    """
    INSERT INTO memories (content, embedding, session_id, source)
    VALUES (:content, CAST(:embedding AS vector), NULL, 'journal')
    RETURNING id, content, created_at
    """
)

EXTRACTION_SYSTEM_PROMPT = (
    "You extract durable facts worth remembering long-term about the user "
    "from a single chat exchange (their message and the assistant's reply "
    "below). Only include facts that would still be useful in unrelated "
    "future conversations: stable identity details, preferences, recurring "
    "commitments or routines, relationships, ongoing projects, and "
    "important dates or deadlines. Do NOT include one-off requests, small "
    "talk, or anything only relevant to this immediate exchange.\n\n"
    'Respond with ONLY a JSON array of short, standalone, third-person '
    'statements about "the user" (e.g. ["The user\'s dentist appointment '
    'repeats on the first Tuesday of every month."]). If there is nothing '
    "worth remembering, respond with []."
)


@dataclass
class RetrievedMemory:
    id: int
    content: str
    distance: float


async def fetch_relevant_memories(
    db: AsyncSession, embedding: list[float], top_k: int = DEFAULT_TOP_K
) -> list[RetrievedMemory]:
    result = await db.execute(
        _SEARCH_SQL, {"query_vector": format_vector_literal(embedding), "top_k": top_k}
    )
    return [
        RetrievedMemory(id=row.id, content=row.content, distance=row.distance) for row in result
    ]


def format_memory_context(memories: list[RetrievedMemory]) -> str:
    bullets = "\n".join(f"- {m.content}" for m in memories)
    return (
        "The following facts were remembered from earlier conversations with "
        "this user and may be relevant to their message below. Use them to "
        "inform your answer when relevant; ignore them if they aren't, and "
        "don't mention this note.\n\n" + bullets
    )


def parse_extracted_facts(raw_content: str) -> list[str]:
    """Lenient JSON-array parsing of the extraction model's reply — local
    models sometimes wrap the array in prose or a code fence despite the
    prompt asking for JSON only. Falls back to an empty list (nothing gets
    remembered) rather than raising, so a malformed extraction reply can
    never block a chat send.
    """
    stripped = raw_content.strip()
    start, end = stripped.find("["), stripped.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        parsed = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


async def store_memories(
    db: AsyncSession, session_id: int, facts: list[str], embeddings: list[list[float]]
) -> None:
    for fact, embedding in zip(facts, embeddings, strict=True):
        await db.execute(
            _INSERT_SQL,
            {"content": fact, "embedding": format_vector_literal(embedding), "session_id": session_id},
        )
    await db.commit()


async def store_journal_memory(db: AsyncSession, content: str, embedding: list[float]):
    """Inserts a user-written journal/quick-note as a Memory row
    (source='journal') and returns the created row (id, content,
    created_at) via RETURNING, so the router can hand it straight back in
    the response without a second query."""
    result = await db.execute(
        _INSERT_JOURNAL_SQL,
        {"content": content, "embedding": format_vector_literal(embedding)},
    )
    row = result.first()
    await db.commit()
    return row


async def list_memories(db: AsyncSession, limit: int = 200):
    """Every stored fact, most-recent-first, for the Memory page. Returns
    plain SQLAlchemy Row objects (id, content, session_id, created_at) —
    never touches `embedding`, so this needs no pgvector codec."""
    result = await db.execute(_LIST_SQL, {"limit": limit})
    return result.all()


async def update_memory_content(
    db: AsyncSession, memory_id: int, content: str, embedding: list[float]
):
    """Overwrites a fact's text and re-embeds it in one statement. Returns
    the updated row, or None if no memory with that id exists."""
    result = await db.execute(
        _UPDATE_SQL,
        {"content": content, "embedding": format_vector_literal(embedding), "id": memory_id},
    )
    row = result.first()
    await db.commit()
    return row


async def delete_memory(db: AsyncSession, memory_id: int) -> bool:
    result = await db.execute(_DELETE_SQL, {"id": memory_id})
    await db.commit()
    return result.rowcount > 0
