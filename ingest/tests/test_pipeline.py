from io import BytesIO
from unittest.mock import patch

import pytest
from jarvis_shared.db import Base
from jarvis_shared.models import FileChunk, StoredFile
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.embeddings import EmbeddingError
from app.image_description import ImageDescriptionError
from app.pipeline import extract_text, is_image, is_pdf, is_supported_text, run_pipeline


class _FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


def _settings(**overrides) -> Settings:
    return Settings(
        database_url="postgresql://x/y",
        chunk_size_chars=overrides.pop("chunk_size_chars", 20),
        chunk_overlap_chars=overrides.pop("chunk_overlap_chars", 5),
        **overrides,
    )


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def _add_file(session, **kwargs) -> StoredFile:
    file = StoredFile(
        filename=kwargs.get("filename", "hello.txt"),
        content_type=kwargs.get("content_type", "text/plain"),
        size=kwargs.get("size", 100),
        object_key=kwargs.get("object_key", "key1"),
    )
    session.add(file)
    await session.commit()
    await session.refresh(file)
    return file


def _fake_get_object(objects: dict[str, bytes]):
    def _get_object(settings, key: str) -> bytes:
        return objects[key]

    return _get_object


@pytest.mark.asyncio
async def test_successful_ingestion_marks_file_and_writes_chunks(session):
    file = await _add_file(session, object_key="k1")

    async def fake_embed(settings, chunks):
        return [[0.1, 0.2, 0.3] for _ in chunks]

    with (
        patch("app.pipeline.storage.get_object", side_effect=_fake_get_object({"k1": b"a" * 30})),
        patch("app.pipeline.embed_chunks", side_effect=fake_embed),
    ):
        succeeded, failed = await run_pipeline(session, _settings())

    assert (succeeded, failed) == (1, 0)

    await session.refresh(file)
    assert file.ingested_at is not None

    result = await session.execute(select(FileChunk).where(FileChunk.file_id == file.id))
    chunks = result.scalars().all()
    assert len(chunks) == 2  # 30 chars / (chunk_size=20, overlap=5, step=15) -> 2 chunks
    assert [c.chunk_index for c in chunks] == [0, 1]


@pytest.mark.asyncio
async def test_failed_embedding_leaves_file_unprocessed_and_writes_no_chunks(session):
    file = await _add_file(session, object_key="k2")

    async def fake_embed_fail(settings, chunks):
        raise EmbeddingError("boom")

    with (
        patch("app.pipeline.storage.get_object", side_effect=_fake_get_object({"k2": b"some text content"})),
        patch("app.pipeline.embed_chunks", side_effect=fake_embed_fail),
    ):
        succeeded, failed = await run_pipeline(session, _settings())

    assert (succeeded, failed) == (0, 1)

    await session.refresh(file)
    assert file.ingested_at is None

    result = await session.execute(select(FileChunk).where(FileChunk.file_id == file.id))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_unsupported_content_type_is_skipped_but_stamped(session):
    file = await _add_file(
        session,
        object_key="k3",
        filename="report.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    succeeded, failed = await run_pipeline(session, _settings())

    assert (succeeded, failed) == (1, 0)

    await session.refresh(file)
    assert file.ingested_at is not None

    result = await session.execute(select(FileChunk).where(FileChunk.file_id == file.id))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_image_file_is_described_chunked_and_embedded(session):
    file = await _add_file(session, object_key="k7", filename="photo.png", content_type="image/png")

    async def fake_describe(settings, filename, content_type, raw):
        return "a" * 30

    async def fake_embed(settings, chunks):
        return [[0.1, 0.2, 0.3] for _ in chunks]

    with (
        patch("app.pipeline.storage.get_object", side_effect=_fake_get_object({"k7": b"fake-png-bytes"})),
        patch("app.pipeline.describe_image", side_effect=fake_describe),
        patch("app.pipeline.embed_chunks", side_effect=fake_embed),
    ):
        succeeded, failed = await run_pipeline(session, _settings())

    assert (succeeded, failed) == (1, 0)

    await session.refresh(file)
    assert file.ingested_at is not None

    result = await session.execute(select(FileChunk).where(FileChunk.file_id == file.id))
    chunks = result.scalars().all()
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_image_description_failure_leaves_file_unprocessed(session):
    file = await _add_file(session, object_key="k8", filename="photo.png", content_type="image/png")

    async def fake_describe_fail(settings, filename, content_type, raw):
        raise ImageDescriptionError("boom")

    with (
        patch("app.pipeline.storage.get_object", side_effect=_fake_get_object({"k8": b"fake-png-bytes"})),
        patch("app.pipeline.describe_image", side_effect=fake_describe_fail),
    ):
        succeeded, failed = await run_pipeline(session, _settings())

    assert (succeeded, failed) == (0, 1)

    await session.refresh(file)
    assert file.ingested_at is None

    result = await session.execute(select(FileChunk).where(FileChunk.file_id == file.id))
    assert result.scalars().all() == []


def test_is_image_by_content_type():
    assert is_image("photo.png", "image/png") is True
    assert is_image("doc.pdf", "application/pdf") is False


def test_is_image_by_extension_when_content_type_missing():
    assert is_image("photo.jpg", None) is True
    assert is_image("doc.txt", None) is False


@pytest.mark.asyncio
async def test_already_ingested_files_are_not_reprocessed(session):
    await _add_file(session, object_key="k4")
    result = await session.execute(select(StoredFile))
    file = result.scalar_one()
    from datetime import UTC, datetime

    file.ingested_at = datetime.now(UTC)
    await session.commit()

    with patch("app.pipeline.storage.get_object") as mock_get_object:
        succeeded, failed = await run_pipeline(session, _settings())

    assert (succeeded, failed) == (0, 0)
    mock_get_object.assert_not_called()


def _blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_is_pdf_by_content_type():
    assert is_pdf("doc.pdf", "application/pdf") is True
    assert is_pdf("doc.pdf", "text/plain") is False


def test_is_pdf_by_extension_when_content_type_missing():
    assert is_pdf("doc.pdf", None) is True
    assert is_pdf("doc.txt", None) is False


def test_is_supported_text_includes_pdf():
    assert is_supported_text("doc.pdf", "application/pdf") is True
    assert is_supported_text("doc.pdf", None) is True


def test_extract_text_falls_back_to_decode_for_plain_text():
    assert extract_text("doc.txt", "text/plain", b"hello") == "hello"


def test_extract_text_reads_pdf_pages():
    assert extract_text("doc.pdf", "application/pdf", _blank_pdf_bytes()) == ""


@pytest.mark.asyncio
async def test_pdf_file_is_extracted_chunked_and_embedded(session):
    file = await _add_file(session, object_key="k5", filename="doc.pdf", content_type="application/pdf")

    async def fake_embed(settings, chunks):
        return [[0.1, 0.2, 0.3] for _ in chunks]

    with (
        patch("app.pipeline.storage.get_object", side_effect=_fake_get_object({"k5": _blank_pdf_bytes()})),
        patch("app.pipeline.extract_text", return_value="a" * 30),
        patch("app.pipeline.embed_chunks", side_effect=fake_embed),
    ):
        succeeded, failed = await run_pipeline(session, _settings())

    assert (succeeded, failed) == (1, 0)

    await session.refresh(file)
    assert file.ingested_at is not None

    result = await session.execute(select(FileChunk).where(FileChunk.file_id == file.id))
    assert len(result.scalars().all()) == 2


@pytest.mark.asyncio
async def test_unparseable_pdf_is_skipped_but_stamped(session):
    file = await _add_file(session, object_key="k6", filename="broken.pdf", content_type="application/pdf")

    with patch("app.pipeline.storage.get_object", side_effect=_fake_get_object({"k6": b"not a real pdf"})):
        succeeded, failed = await run_pipeline(session, _settings())

    assert (succeeded, failed) == (1, 0)

    await session.refresh(file)
    assert file.ingested_at is not None

    result = await session.execute(select(FileChunk).where(FileChunk.file_id == file.id))
    assert result.scalars().all() == []
