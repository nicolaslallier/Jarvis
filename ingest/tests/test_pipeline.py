from unittest.mock import patch

import pytest
from jarvis_shared.db import Base
from jarvis_shared.models import FileChunk, StoredFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.embeddings import EmbeddingError
from app.pipeline import run_pipeline


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
    file = await _add_file(session, object_key="k3", filename="image.png", content_type="image/png")

    succeeded, failed = await run_pipeline(session, _settings())

    assert (succeeded, failed) == (1, 0)

    await session.refresh(file)
    assert file.ingested_at is not None

    result = await session.execute(select(FileChunk).where(FileChunk.file_id == file.id))
    assert result.scalars().all() == []


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
