from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.vector_format import format_vector_literal

DEFAULT_TOP_K = 4

_SEARCH_SQL = text(
    """
    SELECT fc.file_id, f.filename, fc.chunk_index, fc.chunk_text,
           (fc.embedding <=> CAST(:query_vector AS vector)) AS distance
    FROM file_chunks fc
    JOIN files f ON f.id = fc.file_id
    ORDER BY distance ASC
    LIMIT :top_k
    """
)


@dataclass
class RetrievedChunk:
    file_id: int
    filename: str
    chunk_index: int
    chunk_text: str
    distance: float


async def fetch_relevant_chunks(
    db: AsyncSession, embedding: list[float], top_k: int = DEFAULT_TOP_K
) -> list[RetrievedChunk]:
    result = await db.execute(
        _SEARCH_SQL, {"query_vector": format_vector_literal(embedding), "top_k": top_k}
    )
    return [
        RetrievedChunk(
            file_id=row.file_id,
            filename=row.filename,
            chunk_index=row.chunk_index,
            chunk_text=row.chunk_text,
            distance=row.distance,
        )
        for row in result
    ]


def format_context(chunks: list[RetrievedChunk]) -> str:
    sections = [f"[{c.filename}, chunk {c.chunk_index}]\n{c.chunk_text}" for c in chunks]
    return (
        "The following excerpts were retrieved from the user's uploaded documents "
        "and may be relevant to their message below. Use them to inform your answer "
        "when relevant; ignore them if they aren't, and don't mention this note.\n\n"
        + "\n\n---\n\n".join(sections)
    )
