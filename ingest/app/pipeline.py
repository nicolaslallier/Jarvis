import asyncio
import logging
from datetime import UTC, datetime
from io import BytesIO

from botocore.exceptions import BotoCoreError, ClientError
from jarvis_shared import storage
from jarvis_shared.models import FileChunk, StoredFile
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking import chunk_text
from app.config import Settings
from app.embeddings import EmbeddingError, embed_chunks
from app.image_description import ImageDescriptionError, describe_image, describe_pdf_pages
from app.pdf_render import PdfRenderError, render_pdf_pages_to_png

logger = logging.getLogger(__name__)

_TEXT_CONTENT_TYPE_PREFIXES = ("text/",)
_TEXT_CONTENT_TYPES = {"application/json"}
_TEXT_FILE_EXTENSIONS = (".txt", ".md")
_PDF_CONTENT_TYPE = "application/pdf"
_PDF_FILE_EXTENSION = ".pdf"
_IMAGE_CONTENT_TYPE_PREFIX = "image/"
_IMAGE_FILE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def is_pdf(filename: str, content_type: str | None) -> bool:
    if content_type:
        return content_type == _PDF_CONTENT_TYPE
    return filename.lower().endswith(_PDF_FILE_EXTENSION)


def is_image(filename: str, content_type: str | None) -> bool:
    if content_type:
        return content_type.startswith(_IMAGE_CONTENT_TYPE_PREFIX)
    return filename.lower().endswith(_IMAGE_FILE_EXTENSIONS)


def is_supported_text(filename: str, content_type: str | None) -> bool:
    """Plainly-text content and PDFs are extracted directly. Images are
    handled separately via describe_image (there's no text to extract from
    raw image bytes). Other binary formats (DOCX) are a deliberately
    deferred follow-up."""
    if is_pdf(filename, content_type):
        return True
    if content_type:
        return content_type.startswith(_TEXT_CONTENT_TYPE_PREFIXES) or content_type in _TEXT_CONTENT_TYPES
    return filename.lower().endswith(_TEXT_FILE_EXTENSIONS)


def extract_text(filename: str, content_type: str | None, raw: bytes) -> str:
    """Raises on a PDF pypdf can't parse at all; callers treat that as a
    permanent, unretryable failure for the file (same as an unsupported
    content-type) rather than looping forever on the next trigger."""
    if is_pdf(filename, content_type):
        reader = PdfReader(BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return raw.decode("utf-8", errors="replace")


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
    image = is_image(file.filename, file.content_type)
    if not image and not is_supported_text(file.filename, file.content_type):
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

    if image:
        try:
            text = await describe_image(settings, file.filename, file.content_type, raw)
        except ImageDescriptionError:
            logger.exception("ingest: failed to describe image for file_id=%s", file.id)
            return False
    else:
        try:
            text = extract_text(file.filename, file.content_type, raw)
        except Exception:
            logger.exception("ingest: failed to extract text from file_id=%s filename=%s", file.id, file.filename)
            file.ingested_at = datetime.now(UTC)
            await session.commit()
            return True

        if is_pdf(file.filename, file.content_type) and not text.strip():
            try:
                page_images = render_pdf_pages_to_png(raw, settings.pdf_ocr_max_pages)
                text = await describe_pdf_pages(settings, file.filename, page_images)
            except (PdfRenderError, ImageDescriptionError):
                logger.exception("ingest: failed to OCR scanned pdf via vision model for file_id=%s", file.id)
                return False

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
