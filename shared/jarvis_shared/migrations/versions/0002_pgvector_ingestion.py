"""add pgvector extension, files.ingested_at, and file_chunks table

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-09

"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from jarvis_shared.models import EMBEDDING_DIMENSIONS

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Requires a Postgres superuser to have already made the `vector`
    # extension available in this database's image/cluster — see the
    # "Prerequisite before running ingestion" section in CLAUDE.md. If the
    # `jarvis` app role lacks CREATE EXTENSION privilege, this raises a clear
    # permissions error; that's the signal to go do the Infra-repo step
    # first, not a bug in this migration.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("files", sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "file_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "file_id", sa.Integer(), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("file_chunks")
    op.drop_column("files", "ingested_at")
    # Deliberately not dropping the `vector` extension — other objects might
    # depend on it, and DROP EXTENSION is destructive; leave that to a
    # manual decision if it's ever actually needed.
