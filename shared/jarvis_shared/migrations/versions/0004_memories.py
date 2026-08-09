"""add memories table

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-09

"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from jarvis_shared.models import EMBEDDING_DIMENSIONS

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `vector` extension already created by 0003 — no CREATE EXTENSION needed
    # here.
    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("memories")
