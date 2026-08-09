"""Pure metadata-shape checks — no DB engine involved.

FileChunk's `embedding` column uses pgvector's Postgres-only `vector` type,
so these tests inspect SQLAlchemy Table/Column objects directly rather than
running `create_all` against SQLite (which can't express `CREATE EXTENSION
vector` or the `vector(N)` column type). See shared/tests/test_migrations.py
for the one test that does need a live pgvector-enabled Postgres.
"""

from jarvis_shared.models import EMBEDDING_DIMENSIONS, FileChunk, Folder, StoredFile


def test_file_chunk_table_shape():
    table = FileChunk.__table__
    assert table.name == "file_chunks"
    assert {c.name for c in table.columns} == {
        "id",
        "file_id",
        "chunk_index",
        "chunk_text",
        "embedding",
        "created_at",
    }


def test_file_chunk_file_id_cascades_on_delete():
    fk = next(iter(FileChunk.__table__.columns["file_id"].foreign_keys))
    assert fk.column.table.name == "files"
    assert fk.ondelete == "CASCADE"


def test_file_chunk_embedding_dimension_matches_constant():
    embedding_type = FileChunk.__table__.columns["embedding"].type
    assert embedding_type.dim == EMBEDDING_DIMENSIONS


def test_stored_file_has_nullable_ingested_at_column():
    table = StoredFile.__table__
    assert "ingested_at" in table.columns
    assert table.columns["ingested_at"].nullable


def test_folder_parent_cascades_on_delete():
    fk = next(iter(Folder.__table__.columns["parent_id"].foreign_keys))
    assert fk.column.table.name == "folders"
    assert fk.ondelete == "CASCADE"
