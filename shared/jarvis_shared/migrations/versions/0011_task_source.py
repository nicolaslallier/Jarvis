"""add tasks.source

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-09

Adds `source` to `tasks`, the same nullable/free-string column
`appointments.source` got in 0010 for the same reason: an email-ingestion
feature (batch/app/jobs/email_ingest.py) parses unread emails and creates
draft `Task` rows (status="pending_review", see backend/app/schemas.py's
TaskStatus) from anything that looks actionable, without a human having
confirmed it's real yet. Unlike appointments, tasks don't need a separate
`pending_review` boolean column — `tasks.status` was already a free string
with no DB enum (see 0006's docstring), so "pending_review" is just a new
allowed value there, the same code-level-constant-not-migration extension
0010's docstring already described for this convention. `source` (NULL for
every row created directly by the user through the app, "email_import" for
rows email_ingest.py creates) is purely additive and nullable, so this
migration doesn't touch any existing row's data.
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("source", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "source")
