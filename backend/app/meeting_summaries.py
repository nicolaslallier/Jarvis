"""DB layer for meeting summaries: records of what was discussed/decided in
a meeting that already happened, embedding-backed like app/memory.py's
Memory rows for semantic search (see app/search_service.py).

Every query here goes through raw SQL rather than the ORM, for the same
reason app/memory.py does: the backend's engine deliberately doesn't
register asyncpg's pgvector codec (see jarvis_shared/db.py), so any ORM
SELECT against MeetingSummary would implicitly fetch the `embedding` column
and fail. Reads that don't need the embedding explicitly list every other
column instead.
"""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.vector_format import format_vector_literal

_COLUMNS = "id, title, meeting_date, participants, content, appointment_id, created_at, updated_at"

_INSERT_SQL = text(
    f"""
    INSERT INTO meeting_summaries (title, meeting_date, participants, content, embedding, appointment_id)
    VALUES (:title, :meeting_date, :participants, :content, CAST(:embedding AS vector), :appointment_id)
    RETURNING {_COLUMNS}
    """
)

_LIST_SQL = text(
    f"""
    SELECT {_COLUMNS}
    FROM meeting_summaries
    ORDER BY meeting_date DESC, id DESC
    LIMIT :limit
    """
)

_GET_SQL = text(f"SELECT {_COLUMNS} FROM meeting_summaries WHERE id = :id")

# Full-row replace, always re-embedding — same simplicity trade-off as
# app/memory.py's update_memory_content: the caller (router) is responsible
# for merging any fields the client omitted onto the current row first, so
# this always receives the complete, final field set.
_UPDATE_SQL = text(
    f"""
    UPDATE meeting_summaries
    SET title = :title, meeting_date = :meeting_date, participants = :participants,
        content = :content, embedding = CAST(:embedding AS vector), appointment_id = :appointment_id
    WHERE id = :id
    RETURNING {_COLUMNS}
    """
)

_DELETE_SQL = text("DELETE FROM meeting_summaries WHERE id = :id")


def embed_source_text(title: str, content: str) -> str:
    """The text actually embedded for semantic search — title folded in
    alongside content since it carries meaning too (mirrors Memory
    embedding just `content`, the only text field it has)."""
    return f"{title}\n\n{content}"


async def create_meeting_summary(
    db: AsyncSession,
    title: str,
    meeting_date: datetime,
    content: str,
    participants: str | None,
    appointment_id: int | None,
    embedding: list[float],
):
    result = await db.execute(
        _INSERT_SQL,
        {
            "title": title,
            "meeting_date": meeting_date,
            "participants": participants,
            "content": content,
            "embedding": format_vector_literal(embedding),
            "appointment_id": appointment_id,
        },
    )
    row = result.first()
    await db.commit()
    return row


async def list_meeting_summaries(db: AsyncSession, limit: int = 200):
    result = await db.execute(_LIST_SQL, {"limit": limit})
    return result.all()


async def get_meeting_summary(db: AsyncSession, meeting_summary_id: int):
    result = await db.execute(_GET_SQL, {"id": meeting_summary_id})
    return result.first()


async def update_meeting_summary(
    db: AsyncSession,
    meeting_summary_id: int,
    title: str,
    meeting_date: datetime,
    content: str,
    participants: str | None,
    appointment_id: int | None,
    embedding: list[float],
):
    result = await db.execute(
        _UPDATE_SQL,
        {
            "id": meeting_summary_id,
            "title": title,
            "meeting_date": meeting_date,
            "participants": participants,
            "content": content,
            "embedding": format_vector_literal(embedding),
            "appointment_id": appointment_id,
        },
    )
    row = result.first()
    await db.commit()
    return row


async def delete_meeting_summary(db: AsyncSession, meeting_summary_id: int) -> bool:
    result = await db.execute(_DELETE_SQL, {"id": meeting_summary_id})
    await db.commit()
    return result.rowcount > 0
