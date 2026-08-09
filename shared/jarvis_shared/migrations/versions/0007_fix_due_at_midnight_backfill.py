"""fix due_at backfilled at UTC midnight to noon UTC

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-09

0006's backfill anchored old date-only `due_date` values at UTC midnight,
which renders as the *previous* evening in every negative-UTC-offset
timezone (e.g. 2026-08-13T00:00:00Z shows as Aug 12, 8pm in America/
Toronto). This corrects any due_at still sitting exactly on a UTC day
boundary — which can only be leftover 0006 backfill data, since every
due_at set through the app (tool calls, the UI's datetime-local input)
carries a real time component — by moving it to noon UTC, matching 0006's
now-fixed backfill logic.

"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE tasks SET due_at = due_at + interval '12 hours' "
        "WHERE due_at IS NOT NULL AND due_at = date_trunc('day', due_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE tasks SET due_at = due_at - interval '12 hours' "
        "WHERE due_at IS NOT NULL AND due_at = date_trunc('day', due_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' + interval '12 hours'"
    )
