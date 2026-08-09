"""baseline: pre-existing tables created via legacy Base.metadata.create_all

Revision ID: 0001
Revises:
Create Date: 2026-08-09

This revision is intentionally a no-op. It exists so Alembic has a known
starting point that assumes items/tasks/chat_sessions/chat_messages/folders/
files already exist in any environment that ran the app before Alembic was
introduced — they were created via Base.metadata.create_all on startup,
which backend/app/main.py still runs for backwards compatibility.

Stamp an existing database at this revision (without trying to re-create
those tables) before running the first real `alembic upgrade head`:

    alembic stamp 0001
"""

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
