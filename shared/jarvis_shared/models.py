from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
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


TASK_STATUSES = ("todo", "doing", "done", "cancelled", "pending_review")
TASK_PRIORITIES = ("low", "normal", "high")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(2000), default=None)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # "pending_review" (see 0011_task_source.py / backend/app/schemas.py's
    # TaskStatus) marks a draft row awaiting user confirmation before it's
    # treated as a real, trusted task — same status-flag convention as
    # Appointment.pending_review, but modeled as a status value here rather
    # than a separate boolean column since Task.status was already a free
    # string with no DB enum (see 0006's docstring).
    status: Mapped[str] = mapped_column(String(20), default="todo")
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    project: Mapped[str | None] = mapped_column(String(100), default=None)
    tags: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), default=None
    )
    recurrence_rule: Mapped[str | None] = mapped_column(String(255), default=None)
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), default=None
    )
    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"), default=None)
    # NULL = created directly by the user through the app (every row before
    # this column existed). batch/app/jobs/email_ingest.py sets
    # "email_import" on draft tasks (status="pending_review") it extracts
    # from unread emails — same source-tagging convention as
    # Appointment.source (see migration 0010's docstring). See migration
    # 0011_task_source.py.
    source: Mapped[str | None] = mapped_column(String(50), default=None)
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
    # NULL = extracted from a chat exchange by backend/app/memory.py's
    # extraction path (every row today, since that's the only current
    # writer). A future direct-journal-entry feature can set an explicit
    # value (e.g. "journal") to distinguish facts the user wrote themselves
    # from ones the chat model inferred. See migration 0010's docstring.
    source: Mapped[str | None] = mapped_column(String(50), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(2000), default=None)
    location: Mapped[str | None] = mapped_column(String(255), default=None)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(default=False)
    # NULL = created directly by the user through the app (every row today).
    # A future email-ingestion feature will set this (e.g. "email_ingestion")
    # on draft appointments it creates. See migration 0010's docstring.
    source: Mapped[str | None] = mapped_column(String(50), default=None)
    # True = a draft row (e.g. from the future email-ingestion feature above)
    # awaiting user confirmation before it's treated as a real, trusted
    # appointment. False for every appointment created through the existing
    # manual flow, which needs no confirmation step.
    pending_review: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NotificationSent(Base):
    """Dedupe log for reminder notifications: "have we already notified the
    user about this thing today". `kind` identifies what *type* of thing
    (e.g. "task_due", "appointment_reminder") and `entity_id` is that
    thing's primary key in its own table — deliberately not a foreign key,
    since `entity_id` points at a different table depending on `kind`
    (a polymorphic association Postgres FKs can't express directly) and,
    more importantly, because a task/appointment can legitimately be
    deleted *after* being notified about — the notification already did its
    job by then, and a dangling row here is harmless (nothing joins against
    it besides the exact-match dedupe lookup below). That's simpler and
    cheaper than building cross-table cascade-delete tracking for what is
    purely an advisory log. See migration 0009's docstring for the full
    reasoning.
    """

    __tablename__ = "notifications_sent"
    __table_args__ = (
        UniqueConstraint(
            "kind", "entity_id", "notified_date", name="uq_notifications_sent_kind_entity_id_date"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int] = mapped_column(Integer)
    notified_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Habit(Base):
    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # Free string (e.g. "daily"/"weekly"), same convention as Task.status/
    # Task.priority — no DB enum, validated at the Pydantic schema layer.
    frequency: Mapped[str] = mapped_column(String(20))
    streak_count: Mapped[int] = mapped_column(Integer, default=0)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contact(Base):
    """A contact and a single important date about them (birthday,
    anniversary, renewal), deliberately kept as one table rather than a
    normalized `contacts` + `contact_dates` split. Nothing in the current
    feature set needs more than one date per contact; splitting now would
    be premature normalization for a one-to-many relationship this app
    doesn't yet exercise. See migration 0010's docstring.
    """

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    date: Mapped[date] = mapped_column(Date)
    # Free string (e.g. "birthday"/"anniversary"/"renewal"), same
    # no-DB-enum convention as Task.status/Task.priority.
    date_type: Mapped[str] = mapped_column(String(20))
    recurring_yearly: Mapped[bool] = mapped_column(default=True)
    reminder_lead_days: Mapped[int] = mapped_column(Integer, default=7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Bill(Base):
    """A recurring bill reminder. Deliberately no paid/status tracking in
    this pass — see migration 0010's docstring for why that's a separate,
    deferred design question (modeling per-cycle bill instances) rather
    than an oversight here.
    """

    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    due_day: Mapped[int] = mapped_column(Integer)
    # Free string (e.g. "monthly"/"yearly"), same no-DB-enum convention as
    # Task.status/Task.priority.
    recurrence: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingSummary(Base):
    """A record of what was discussed/decided in a meeting that already
    happened — distinct from Appointment, which models a *scheduled* event
    (start/end time), not what came out of it. Embedding-backed like Memory/
    FileChunk so it's retrievable via app/search_service.py's semantic
    search leg; the backend engine doesn't register the pgvector codec (see
    jarvis_shared/db.py), so backend code must read/write `embedding` via
    raw SQL CAST(... AS vector), never the ORM, same as Memory/FileChunk.
    """

    __tablename__ = "meeting_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    meeting_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    participants: Mapped[str | None] = mapped_column(String(1000), default=None)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    # Optional link back to the calendar event this summary was taken for.
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
