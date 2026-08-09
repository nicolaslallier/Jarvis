import asyncio
import logging
from datetime import UTC, datetime

from botocore.exceptions import BotoCoreError, ClientError
from jarvis_shared import storage
from jarvis_shared.models import FileChunk, StoredFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking import chunk_text
from app.config import Settings
from app.embeddings import EmbeddingError, embed_chunks

logger = logging.getLogger(__name__)

_TEXT_CONTENT_TYPE_PREFIXES = ("text/",)
_TEXT_CONTENT_TYPES = {"application/json"}
_TEXT_FILE_EXTENSIONS = (".txt", ".md")


def is_supported_text(filename: str, content_type: str | None) -> bool:
    """Only plainly-text content is extracted in this first pass. Binary
    formats (PDF, DOCX, images) are a deliberately deferred follow-up."""
    if content_type:
        return content_type.startswith(_TEXT_CONTENT_TYPE_PREFIXES) or content_type in _TEXT_CONTENT_TYPES
    return filename.lower().endswith(_TEXT_FILE_EXTENSIONS)


async def fetch_pending_files(session: AsyncSession) -> list[StoredFile]:
    result = await session.execute(select(StoredFile).where(StoredFile.ingested_at.is_(None)))
    return list(result.scalars().all())


async def persist_chunks(
    session: AsyncSession, file_id: int, chunks: list[str], embeddings: list[list[float]]
) -> None:
    """Split out from process_file so tests can swap this out without a real
    pgvector-backed database."""
    session.add_all(
        FileChunk(file_id=file_id, chunk_index=index, chunk_text=text, embedding=embedding)
        for index, (text, embedding) in enumerate(zip(chunks, embeddings, strict=True))
    )


async def process_file(session: AsyncSession, settings: Settings, file: StoredFile) -> bool:
    """Process one file. Returns True if it's now considered done (ingested,
    or deliberately skipped as unsupported) and False if it should be
    retried on the next trigger."""
    if not is_supported_text(file.filename, file.content_type):
        logger.info(
            "ingest: skipping unsupported content-type filename=%s content_type=%s",
            file.filename,
            file.content_type,
        )
        file.ingested_at = datetime.now(UTC)
        await session.commit()
        return True

    try:
        raw = await asyncio.to_thread(storage.get_object, settings, file.object_key)
    except (BotoCoreError, ClientError):
        logger.exception("ingest: failed to fetch %s from MinIO", file.object_key)
        return False

    text = raw.decode("utf-8", errors="replace")
    chunks = chunk_text(
        text, chunk_size_chars=settings.chunk_size_chars, chunk_overlap_chars=settings.chunk_overlap_chars
    )
    if not chunks:
        file.ingested_at = datetime.now(UTC)
        await session.commit()
        return True

    try:
        embeddings = await embed_chunks(settings, chunks)
    except EmbeddingError:
        logger.exception("ingest: failed to embed chunks for file_id=%s", file.id)
        return False

    await persist_chunks(session, file.id, chunks, embeddings)
    file.ingested_at = datetime.now(UTC)
    await session.commit()
    return True


async def run_pipeline(session: AsyncSession, settings: Settings) -> tuple[int, int]:
    """Runs one ingestion pass. Returns (succeeded_count, failed_count)."""
    pending = await fetch_pending_files(session)
    logger.info("ingest: %d pending file(s)", len(pending))

    succeeded = 0
    failed = 0
    for file in pending:
        if await process_file(session, settings, file):
            succeeded += 1
        else:
            failed += 1
    return succeeded, failed
