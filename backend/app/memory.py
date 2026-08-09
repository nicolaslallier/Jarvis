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
