from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jarvis_shared.db import Base

# Must match whatever embedding model is actually loaded into LM Studio (see
# ingest/app/config.py's EMBEDDING_LMSTUDIO_MODEL default). Switching to a
# model with a different output dimension later requires a new Alembic
# migration that alters this column's type *and* re-embeds every existing
# chunk — vectors from a different dimension aren't just resizable, they're
# meaningless.
EMBEDDING_DIMENSIONS = 768


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(2000), default=None)
    due_date: Mapped[date | None] = mapped_column(Date, default=None)
    done: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["ChatMessageRecord"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessageRecord.id",
    )


class ChatMessageRecord(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="CASCADE"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StoredFile(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(255), default=None)
    size: Mapped[int] = mapped_column(BigInteger)
    # Path inside the MinIO bucket, prefixed with a UUID so same-named
    # uploads never collide.
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="CASCADE"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # NULL = not yet processed by the RAG ingestion pipeline; a timestamp =
    # ingested at that time. See ingest/app/pipeline.py.
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class FileChunk(Base):
    __tablename__ = "file_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Memory(Base):
    """A durable fact learned about the user from a chat exchange (identity,
    preferences, recurring commitments, ongoing projects — see
    backend/app/memory.py's extraction prompt for the exact criteria), kept
    across chat sessions and retrieved by embedding similarity on later
    messages. The counterpart to FileChunk, but for facts learned in
    conversation rather than uploaded documents.
    """

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    # The session the fact was learned in, kept only for traceability — not
    # used to scope retrieval, since the whole point is recall *across*
    # sessions. SET NULL on session delete so deleting a chat thread doesn't
    # discard facts already folded into long-term memory.
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
