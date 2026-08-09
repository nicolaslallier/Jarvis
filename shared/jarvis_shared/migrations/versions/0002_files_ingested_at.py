"""add files.ingested_at

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-09

Split out from what was originally a single "pgvector + ingested_at +
file_chunks" migration. `ingested_at` is read by every GET /files response
(see backend/app/routers/files.py) regardless of whether the RAG ingestion
feature is usable yet, but the rest of that original migration requires the
`vector` Postgres extension to already be installed in the cluster's image —
an Infra-repo prerequisite (see CLAUDE.md's "Prerequisite before running
ingestion") that can lag behind this migration being written. Keeping this
column on its own revision means `alembic upgrade head` up to here (and thus
the Files feature) doesn't have to wait on that Infra-side step; only the
pgvector-dependent revision does.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("files", sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("files", "ingested_at")
