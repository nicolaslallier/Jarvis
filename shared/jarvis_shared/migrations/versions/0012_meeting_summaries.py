"""add meeting_summaries table

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-10

Meeting summaries capture what was discussed/decided in a meeting that
already happened — distinct from `appointments`, which schedules a future
event and has no notion of its outcome. Embedding-backed like `memories`/
`file_chunks` so it's semantically searchable; the `vector` extension is
already created by 0003, so no CREATE EXTENSION is needed here.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from jarvis_shared.models import EMBEDDING_DIMENSIONS

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("meeting_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("participants", sa.String(length=1000), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "appointment_id",
            sa.Integer(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("meeting_summaries")
